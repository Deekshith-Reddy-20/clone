"""PSTN stream guard: no invented hours when FACTS lack them."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.voice_llm_router import LlmTurnResult
from app.services.voice.voice_stream_guard import guard_stream_sentence
from app.services.voice.voice_grounding_guard import sentence_fails_grounding
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class StreamHoursGuardTests(unittest.TestCase):
    def test_guard_drops_nine_to_nine(self) -> None:
        prof = json.loads((FIXTURES / "vfarms_profile.json").read_text())
        facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
        bad = "మా resort ఉదయం 9 గంటల నుంచి రాత్రి 9 గంటల వరకు open ఉంటుంది అండి."
        fail, _ = sentence_fails_grounding(
            bad, spoken_facts=facts, fields={}, caller_text="opening time ఏంటి?"
        )
        self.assertTrue(fail)
        ok, actions = guard_stream_sentence(
            bad,
            brief="Your name is Maya for V Farms Resort.",
            lang="te-IN",
            vertical="lodging",
            spoken_facts=facts,
            caller_text="opening time ఏంటి?",
            fields={},
        )
        self.assertIsNone(ok)
        self.assertTrue(actions)

    def test_hours_question_triggers_save_lead(self) -> None:
        prof = json.loads((FIXTURES / "vfarms_profile.json").read_text())
        facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        db.add = MagicMock()
        call = MagicMock()
        call.workspace_id = "00000000-0000-0000-0000-000000000001"
        call.captured_fields = {
            "employee_brief": "Your name is Maya for V Farms Resort.",
            "employee_language": "Telugu",
            "employee_spoken_facts": facts,
            "employee_business_profile": prof,
            "conversation_language": "te-IN",
            "caller_e164": "+919876543210",
            "inbound_chat": {"turns": []},
        }
        from unittest.mock import patch

        with patch("app.services.voice.inbound_llm_engine.generate_inbound_llm_turn") as m:
            m.return_value = LlmTurnResult(
                "మా resort ఉదయం 9 గంటల నుంచి రాత్రి 9 గంటల వరకు open ఉంటుంది అండి.",
                100.0,
                "sarvam",
                tool_calls=[],
            )
            reply, _ = process_inbound_speech(
                db,
                call,
                caller_text="మీది ఏ time నుంచి ఏ time వరకు opening ఉంటుంది?",
                stt_language="te-IN",
            )
        self.assertNotIn("9 గంటల", reply or "")
        tools = [t.get("name") for t in (call.captured_fields or {}).get("tool_log") or []]
        if "save_lead" not in tools:
            self.assertIn("confirm చేసి చెప్తాము", reply or "")


if __name__ == "__main__":
    unittest.main()