"""Live test: forced Sarvam timeout triggers Gemini failover."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.voice.gemini import gemini_configured
from app.services.voice.inbound_conversation import process_inbound_speech


@pytest.mark.live_llm
def test_sarvam_timeout_failover_to_gemini(capsys) -> None:
    if os.getenv("KARYUK_RUN_LIVE_LLM") != "1":
        pytest.skip("Set KARYUK_RUN_LIVE_LLM=1")
    os.environ["KARYUK_FORCE_SARVAM_TIMEOUT"] = "1"
    try:
        import json
        from pathlib import Path

        profile = json.loads(
            (Path(__file__).parent / "fixtures" / "vfarms_profile.json").read_text(encoding="utf-8")
        )
        call = MagicMock()
        call.employee_id = None
        call.workspace_id = None
        call.captured_fields = {
            "employee_brief": "Your name is Maya for V Farms Resort.",
            "employee_spoken_facts": render_profile_facts(BusinessProfile.from_snapshot(profile)),
            "employee_business_profile": profile,
            "voice_grounding_pinned": True,
            "inbound_chat": {"turns": []},
        }
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        reply, _ = process_inbound_speech(
            db,
            call,
            caller_text="Please tell me briefly where V Farms Resort is located.",
            stt_language="en-IN",
        )
        fields = call.captured_fields or {}
        print(f"reply: {reply}")
        print(f"failover: {fields.get('llm_last_failover')}")
        print(f"provider: {fields.get('llm_primary_provider')}")
        assert fields.get("llm_last_failover", {}).get("reason") == "sarvam_ttft_timeout"
        if gemini_configured():
            assert fields.get("llm_primary_provider") == "gemini"
        else:
            pytest.skip("Gemini not configured — failover reason still logged")
    finally:
        os.environ.pop("KARYUK_FORCE_SARVAM_TIMEOUT", None)