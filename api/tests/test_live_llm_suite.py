"""15-conversation live LLM eval — pytest -m live_llm (KARYUK_RUN_LIVE_LLM=1)."""

from __future__ import annotations

import json
import math
import os
import statistics
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.business_profile_render import render_profile_facts
from app.schemas.business_profile import BusinessProfile
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.voice_output_guard import guard_reply_rejected

FIXTURES = Path(__file__).parent / "fixtures"
SUITE = Path(__file__).parent / "conversations" / "live_eval_suite.json"


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] + (values[int(c)] - values[f]) * (k - f)


def _word_count(text: str) -> int:
    return len((text or "").split())


def _load_profile(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert data.get("test_only") is True, f"{name} must be test_only fixture"
    return data


def _call(brief: str, profile: dict, *, caller: str = "+919876543210") -> MagicMock:
    call = MagicMock()
    call.employee_id = None
    call.workspace_id = None
    call.workspace_id = "00000000-0000-0000-0000-000000000001"
    rendered = render_profile_facts(BusinessProfile.from_snapshot(profile))
    call.captured_fields = {
        "employee_brief": brief,
        "employee_operator_instructions": brief,
        "employee_language": "Telugu",
        "employee_spoken_facts": rendered,
        "employee_business_profile": profile,
        "employee_natural_spoken": True,
        "employee_mode": "lodging",
        "conversation_language": "te-IN",
        "voice_grounding_pinned": True,
        "caller_e164": caller,
        "inbound_chat": {"turns": []},
    }
    call.transcript = ""
    call.duration_seconds = 0
    call.outcome = None
    return call


@pytest.mark.live_llm
def test_live_eval_fifteen_conversations(capsys) -> None:
    if os.getenv("KARYUK_RUN_LIVE_LLM") != "1":
        pytest.skip("Set KARYUK_RUN_LIVE_LLM=1")

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    scalar_result = MagicMock()
    scalar_result.first.return_value = None
    db.scalars = MagicMock(return_value=scalar_result)
    db.add = MagicMock()

    ttft_by_provider: dict[str, list[float]] = {}
    all_words: list[int] = []
    guard_rejects = 0
    intent_fires = 0
    total_turns = 0
    tool_expect_ok = 0
    tool_expect_total = 0
    last_reply = ""

    for conv in suite["suites"]:
        profile = _load_profile(conv["profile_fixture"])
        call = _call(conv["brief"], profile)
        print(f"\n=== CONVERSATION {conv['id']} ===")
        for i, step in enumerate(conv["turns"]):
            reply, _ = process_inbound_speech(
                db,
                call,
                caller_text=step["caller"],
                stt_language="te-IN",
            )
            fields = call.captured_fields or {}
            provider = str(fields.get("llm_primary_provider") or "unknown")
            ttft = float(fields.get("llm_last_ttft_ms") or 0)
            ttft_by_provider.setdefault(provider, []).append(ttft)
            wc = _word_count(reply)
            all_words.append(wc)
            total_turns += 1
            _, rej = guard_reply_rejected(reply, brief=conv["brief"], lang="te-IN", last_agent_reply=last_reply)
            if rej:
                guard_rejects += 1
            tools = fields.get("tool_log") or []
            if fields.get("intent_layer_fired"):
                intent_fires += 1
            failover = fields.get("llm_last_failover")
            print(f"turn {i+1} caller: {step['caller']}")
            print(f"  agent ({wc} words): {reply}")
            print(f"  guard_rejected={rej} provider={provider} llm_ttft_ms={ttft} tools={tools[-1:] if tools else []}")
            if failover:
                print(f"  failover={failover}")
            max_w = step.get("max_words", 32)
            assert wc <= max_w + 2, f"{conv['id']} turn {i+1} too long ({wc}>{max_w})"
            for bad in step.get("forbid_substrings", []):
                assert bad not in reply
            if step.get("require_new_detail") and last_reply:
                overlap = len(set(reply.split()) & set(last_reply.split())) / max(len(reply.split()), 1)
                assert overlap < 0.75, "Reply repeated prior turn"
            if step.get("expect_tool_any"):
                tool_expect_total += 1
                names = [t.get("name") for t in tools]
                sources_ok = step.get("tool_sources_ok")
                hit = any(
                    t.get("name") in step["expect_tool_any"]
                    and (not sources_ok or str(t.get("source") or "llm_native") in sources_ok)
                    for t in tools
                )
                if hit:
                    tool_expect_ok += 1
                assert hit, f"expected tool in {names}"
            last_reply = reply

    p50 = {k: statistics.median(v) for k, v in ttft_by_provider.items() if v}
    p95 = {k: _percentile(v, 95) for k, v in ttft_by_provider.items() if v}
    avg_words = statistics.mean(all_words) if all_words else 0
    reject_rate = guard_rejects / max(total_turns, 1)
    tool_acc = tool_expect_ok / max(tool_expect_total, 1)
    print("\n=== SUMMARY ===")
    print(
        f"turns={total_turns} guard_rejection_rate={reject_rate:.2%} "
        f"intent_layer_rate={intent_fires / max(total_turns, 1):.2%} avg_words={avg_words:.1f} "
        f"tool_call_accuracy={tool_acc:.2%} ({tool_expect_ok}/{tool_expect_total})"
    )
    for k in sorted(ttft_by_provider):
        print(f"provider={k} p50={p50.get(k, 0):.1f}ms p95={p95.get(k, 0):.1f}ms n={len(ttft_by_provider[k])}")