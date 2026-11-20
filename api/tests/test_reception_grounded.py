"""Reception answers doubts from published facts before pushing booking."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.voice.employee_playbook import (
    booking_flow_active,
    is_factual_business_question,
    should_prefer_reception_llm,
    should_run_booking_flow,
)
from app.services.voice.inbound_conversation import process_inbound_speech


class _DB:
    def commit(self) -> None:
        pass

    def refresh(self, _c) -> None:
        pass


@skip_unless_legacy
class ReceptionGroundedTests(unittest.TestCase):
    def test_factual_not_forcing_booking_flow(self) -> None:
        fields = {
            "employee_brief": "Maya at V Farms Resort.",
            "employee_website_knowledge": "Pool 8:30 to 10 PM. Near Medchal.",
        }
        self.assertTrue(is_factual_business_question("pool timings ఏంటి?"))
        self.assertFalse(should_run_booking_flow(fields, "pool timings ఏంటి?"))
        self.assertTrue(should_prefer_reception_llm("pool timings ఏంటి?", fields))

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_pool_question_before_booking_prompt(self, _sarvam) -> None:
        call = SimpleNamespace(
            captured_fields={
                "employee_brief": "Your name is Maya for V Farms Resort.",
                "employee_language": "Telugu",
                "employee_website_knowledge": "Pool 8:30 AM to 10 PM daily.",
                "conversation_language": "te-IN",
                "inbound_chat": {"turns": []},
            },
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            reply, _ = process_inbound_speech(
                _DB(),
                call,
                caller_text="మీ pool ఎన్ని గంటల వరకు తెరిచి ఉంటుంది?",
                stt_language="te-IN",
            )
        self.assertIn("8:30", reply)
        self.assertNotIn("చెక్-ఇన్", reply)
        self.assertFalse(booking_flow_active(call.captured_fields))


if __name__ == "__main__":
    unittest.main()