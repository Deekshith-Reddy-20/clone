"""Live LLM eval: V Farms regression against real configured provider (pytest -m live_llm)."""

from __future__ import annotations

import json
import math
import os
import statistics
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import get_settings
from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.telephony.inbound_mode import use_sarvam_inbound_voice
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.voice_output_guard import guard_reply_rejected, llm_hard_fallback

DATA_PATH = Path(__file__).parent / "conversations" / "vfarms_regression.json"
PROFILE_PATH = Path(__file__).parent / "fixtures" / "vfarms_profile.json"


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


def _call(brief: str, facts: str) -> MagicMock:
    profile = BusinessProfile.model_validate(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))
    call = MagicMock()
    call.captured_fields = {
        "employee_brief": brief,
        "employee_operator_instructions": brief,
        "employee_language": "Telugu",
        "employee_website_knowledge": facts,
        "employee_spoken_facts": render_profile_facts(profile),
        "employee_business_profile": profile.model_dump(mode="json"),
        "employee_natural_spoken": True,
        "employee_mode": "lodging",
        "conversation_language": "te-IN",
        "voice_grounding_pinned": True,
        "inbound_chat": {"turns": []},
    }
    call.transcript = ""
    call.summary = ""
    call.duration_seconds = 0
    call.outcome = None
    return call


@pytest.mark.live_llm
def test_vfarms_regression_live_llm(capsys) -> None:
    if os.getenv("KARYUK_RUN_LIVE_LLM") != "1":
        pytest.skip("Set KARYUK_RUN_LIVE_LLM=1 to hit real providers")

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    brief = data["employee"]["brief"]
    facts = data["employee"]["facts"]
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    call = _call(brief, facts)

    ttfts: list[float] = []
    guard_rejects = 0
    provider = "sarvam" if use_sarvam_inbound_voice() else "gemini"
    settings = get_settings()
    model = getattr(settings, "sarvam_chat_model", "") or "sarvam-default"
    if provider != "sarvam":
        model = getattr(settings, "gemini_model", "") or "gemini-default"

    print(f"\n=== live_llm provider={provider} model={model} fallback={'gemini' if provider == 'sarvam' else 'sarvam'} ===")
    print(f"hard_fallback={llm_hard_fallback('te-IN')!r}\n")

    for i, step in enumerate(data["turns"]):
        reply, _ = process_inbound_speech(
            db,
            call,
            caller_text=step["caller"],
            stt_language="te-IN",
        )
        fields = call.captured_fields or {}
        ttft = float(fields.get("llm_last_ttft_ms") or 0)
        if ttft:
            ttfts.append(ttft)
        _, rej = guard_reply_rejected(reply, brief=brief, lang="te-IN")
        if rej:
            guard_rejects += 1
        wc = len(reply.split())
        print(f"turn {i+1} caller: {step['caller']}")
        print(f"  agent ({wc} words): {reply}")
        print(f"  guard_rejected={rej} llm_ttft_ms={ttft}")
        assert wc <= 32, f"turn {i+1} exceeds ~30 words ({wc})"
        for bad in step.get("forbid_substrings", []):
            assert bad not in reply, f"turn {i+1}: forbidden {bad!r}"

    p50 = statistics.median(ttfts) if ttfts else 0.0
    p95 = _percentile(ttfts, 95)
    reject_rate = guard_rejects / max(len(data["turns"]), 1)
    print(f"\nTTFT p50={p50:.1f}ms p95={p95:.1f}ms guard_rejection_rate={reject_rate:.2%}")