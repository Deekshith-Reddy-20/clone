#!/usr/bin/env python3
"""Live eval metrics + save_lead miss classification."""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.voice_fact_guard import (
    classify_save_lead_miss,
    reply_invented_negative,
)
from app.services.voice.voice_location_followup import whatsapp_send_consented
from app.services.voice.voice_output_guard import guard_reply_rejected

SUITE = ROOT / "tests" / "conversations" / "live_eval_suite.json"
NEG_SUITE = ROOT / "tests" / "conversations" / "live_safety_net_negative.json"
FIXTURES = ROOT / "tests" / "fixtures"


def p95(v: list[float]) -> float:
    if not v:
        return 0.0
    v = sorted(v)
    k = 0.95 * (len(v) - 1)
    f = math.floor(k)
    c = math.ceil(k)
    return v[int(k)] if f == c else v[f] + (v[c] - v[f]) * (k - f)


def _tool_names(tools: list) -> list[str]:
    return [str(x.get("name")) for x in tools]


def _expect_hit(
    tools: list,
    expected: list[str],
    *,
    native_only: bool,
    sources_ok: list[str] | None = None,
) -> bool:
    for x in tools:
        name = str(x.get("name"))
        if name not in expected:
            continue
        src = str(x.get("source") or "llm_native")
        if native_only:
            if src != "llm_native":
                continue
        elif sources_ok is not None and src not in sources_ok:
            continue
        return True
    return False


def _run_conv_steps(
    conv: dict,
    *,
    db,
    call,
    facts: str,
    ttft: dict[str, list[float]],
    words: list[int],
    gr: int,
    tot: int,
    tool_ok: int,
    tool_tot: int,
    native_ok: int,
    native_tot: int,
    hallu: int,
    invented: int,
    guard_blocks: int,
    save_miss: list,
    tools_by_source: dict[str, int],
    fp_count: int,
    last: str,
) -> tuple[int, int, int, int, int, int, int, int, int, int, str]:
    for step in conv["turns"]:
        reply, _ = process_inbound_speech(db, call, caller_text=step["caller"], stt_language="te-IN")
        f = call.captured_fields or {}
        p = str(f.get("llm_primary_provider") or "unknown")
        t_ms = float(f.get("llm_last_ttft_ms") or 0)
        ttft.setdefault(p, []).append(t_ms)
        words.append(len((reply or "").split()))
        tot += 1
        _, rej = guard_reply_rejected(reply, brief=conv["brief"], lang="te-IN", last_agent_reply=last)
        gr += int(rej)
        hallu += int(f.get("llm_fact_hallucination") or 0)
        invented += int(f.get("llm_invented_negative") or 0)
        guard_blocks += int(f.get("llm_grounding_block") or 0)
        tools = f.get("tool_log") or []
        for x in tools:
            src = str(x.get("source") or "llm_native")
            tools_by_source[src] = tools_by_source.get(src, 0) + 1
        names = _tool_names(tools)
        src_ok = step.get("tool_sources_ok")
        if step.get("expect_tool_any"):
            tool_tot += 1
            native_tot += 1
            if _expect_hit(tools, step["expect_tool_any"], native_only=False, sources_ok=src_ok):
                tool_ok += 1
            else:
                print(
                    f"TOOL_MISS {conv['id']}: caller={step['caller'][:60]!r} "
                    f"expected={step['expect_tool_any']} got={names}"
                )
            if _expect_hit(tools, step["expect_tool_any"], native_only=True, sources_ok=src_ok):
                native_ok += 1
            else:
                print(
                    f"NATIVE_TOOL_MISS {conv['id']}: caller={step['caller'][:60]!r} "
                    f"expected={step['expect_tool_any']} "
                    f"got={[(x.get('name'), x.get('source')) for x in tools]}"
                )
        if "send_whatsapp_details" in names and not whatsapp_send_consented(
            step["caller"], last_agent_reply=last
        ):
            fp_count += 1
            print(
                f"WHATSAPP_FP {conv['id']}: caller={step['caller'][:60]!r} "
                f"last_agent={last[:80]!r} "
                f"fired send_whatsapp_details without prior offer+yes"
            )
        forbidden = step.get("forbid_tool_any") or []
        if forbidden:
            bad = [n for n in names if n in forbidden]
            if bad:
                fp_count += 1
                print(
                    f"SAFETY_NET_FP {conv['id']}: caller={step['caller'][:60]!r} "
                    f"forbidden={forbidden} fired={bad}"
                )
        if reply_invented_negative(reply or "", facts):
            print(f"INVENTED_NEGATIVE_REPLY {conv['id']}: {reply!r}")
        exp = step.get("expect_tool_any") or []
        if "save_lead" in exp and exp == ["save_lead"]:
            called = "save_lead" in names
            if not called:
                cls = classify_save_lead_miss(step["caller"], reply or "", facts, save_lead_called=called)
                save_miss.append(
                    {
                        "conv": conv["id"],
                        "caller": step["caller"],
                        "reply": reply,
                        "class": cls,
                        "tools": names,
                    }
                )
        for bad in step.get("forbid_substrings", []):
            if bad.lower() in (reply or "").lower():
                print(f"FORBID_SUBSTRING {conv['id']}: {bad!r} in reply")
        last = reply or ""
    return gr, tot, tool_ok, tool_tot, native_ok, native_tot, hallu, invented, guard_blocks, fp_count, last


def main() -> int:
    if os.getenv("KARYUK_RUN_LIVE_LLM") != "1":
        print("Set KARYUK_RUN_LIVE_LLM=1")
        return 2
    primary = (os.getenv("KARYUK_LLM_PRIMARY") or "sarvam").strip().lower()
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    db.add = MagicMock()

    ttft: dict[str, list[float]] = {}
    words: list[int] = []
    gr = tot = 0
    tool_ok = tool_tot = 0
    native_ok = native_tot = 0
    hallu = invented = 0
    guard_blocks = 0
    fp_count = 0
    save_miss: list[dict] = []
    tools_by_source: dict[str, int] = {}

    for path in (SUITE, NEG_SUITE):
        if not path.is_file():
            continue
        suite = json.loads(path.read_text(encoding="utf-8"))
        for conv in suite["suites"]:
            prof = json.loads((FIXTURES / conv["profile_fixture"]).read_text(encoding="utf-8"))
            facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
            call = MagicMock()
            call.workspace_id = None
            call.duration_seconds = 0
            call.captured_fields = {
                "employee_brief": conv["brief"],
                "employee_operator_instructions": conv["brief"],
                "employee_language": "Telugu",
                "employee_spoken_facts": facts,
                "employee_business_profile": prof,
                "employee_natural_spoken": True,
                "conversation_language": "te-IN",
                "caller_e164": "+919876543210",
                "inbound_chat": {"turns": []},
            }
            last = ""
            gr, tot, tool_ok, tool_tot, native_ok, native_tot, hallu, invented, guard_blocks, fp_count, last = _run_conv_steps(
                conv,
                db=db,
                call=call,
                facts=facts,
                ttft=ttft,
                words=words,
                gr=gr,
                tot=tot,
                tool_ok=tool_ok,
                tool_tot=tool_tot,
                native_ok=native_ok,
                native_tot=native_tot,
                hallu=hallu,
                invented=invented,
                guard_blocks=guard_blocks,
                save_miss=save_miss,
                tools_by_source=tools_by_source,
                fp_count=fp_count,
                last=last,
            )

    counts = {"a": 0, "b": 0, "c": 0}
    for row in save_miss:
        counts[row["class"]] = counts.get(row["class"], 0) + 1
        print(f"\n--- save_lead miss [{row['class']}] {row['conv']} ---")
        print(f"caller: {row['caller']}")
        print(f"reply: {row['reply']}")
        print(f"tools: {row['tools']}")

    print(f"\n=== LIVE REPORT primary={primary} ===")
    print(f"turns={tot} avg_words={statistics.mean(words):.1f} guard_rejections={gr}")
    print(
        f"tool_accuracy_combined={tool_ok}/{tool_tot} ({100*tool_ok/max(tool_tot,1):.1f}%)"
    )
    print(
        f"tool_accuracy_native_only={native_ok}/{native_tot} "
        f"({100*native_ok/max(native_tot,1):.1f}%) [llm_native source only]"
    )
    if primary == "sarvam":
        print(f"sarvam_llm_native_tool_accuracy={native_ok}/{native_tot}")
    print(f"tools_by_source={dict(sorted(tools_by_source.items()))}")
    print(f"safety_net_false_positives={fp_count} (must_be_0)")
    print(f"hallucination_regen_events={hallu} invented_negative_regen={invented} grounding_blocks={guard_blocks}")
    print(
        f"save_lead_miss_classify: a_hallucination={counts.get('a',0)} "
        f"b_deflect_no_lead={counts.get('b',0)} c_ok={counts.get('c',0)}"
    )
    for k, v in sorted(ttft.items()):
        print(f"provider={k} n={len(v)} p50={statistics.median(v):.1f}ms p95={p95(v):.1f}ms")
    return 1 if fp_count else 0


if __name__ == "__main__":
    raise SystemExit(main())