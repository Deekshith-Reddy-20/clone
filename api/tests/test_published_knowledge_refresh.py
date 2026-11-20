"""Published knowledge must reach live turns after publish / workspace edits."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.employee_knowledge import refresh_call_grounding
from app.services.voice.employee_playbook import try_brand_knowledge_reply
from app.services.voice.inbound_conversation import process_inbound_speech


class PublishedKnowledgeTests(unittest.TestCase):
    def test_brand_snippet_finds_vform_300(self) -> None:
        know = (
            "V-Form 300 is our weekend farm-stay package at V Farms Resort. "
            "Includes pool access and twin cottages. Fees start at 8500 INR."
        )
        reply = try_brand_knowledge_reply(
            "V-Forms 300 గురించి చెప్పండి",
            brief="Resort receptionist.",
            website_knowledge=know,
            lang="te-IN",
        )
        self.assertIsNotNone(reply)
        self.assertIn("V Farms", reply)
        self.assertTrue("300" in reply or "8500" in reply or "package" in reply.lower())

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_refresh_and_answer_not_course_deflect(self, _sarvam) -> None:
        employee_id = uuid4()
        workspace_id = uuid4()
        know = "V-Form 300 weekend package at V Farms. Call 0404590002 for bookings."

        call = SimpleNamespace(
            id=uuid4(),
            employee_id=employee_id,
            workspace_id=workspace_id,
            captured_fields={
                "employee_brief": "Old course enrollment bot.",
                "employee_language": "Telugu",
                "employee_website_knowledge": "Old stale text only courses.",
                "knowledge_state": "published",
                "inbound_chat": {"turns": []},
            },
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        db = MagicMock()

        def _fake_refresh(_db, _call):
            fields = dict(_call.captured_fields)
            fields["employee_brief"] = "V Farms Resort receptionist."
            fields["employee_website_knowledge"] = know
            _call.captured_fields = fields
            return fields

        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=_fake_refresh,
        ), patch(
            "app.services.voice.inbound_llm_engine.generate_inbound_llm_turn",
            return_value=__import__(
                "app.services.voice.voice_llm_router", fromlist=["LlmTurnResult"]
            ).LlmTurnResult("V-Form 300 weekend package Medchal V Farms అండి.", 50.0, "mock"),
        ):
            reply, _ = process_inbound_speech(
                db,
                call,
                caller_text="లేదు నాకు V-form 300 గురించి కావాలి",
                stt_language="te-IN",
            )
        self.assertNotIn("course", reply.lower())
        self.assertTrue(
            "V Farms" in reply or "300" in reply or "లేవండి" not in reply
        )
        self.assertNotIn("ఈ ఫోన్ కాల్ లో సమాచారం లేదు", reply)


    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_vfarms_booking_not_college_script(self, _sarvam) -> None:
        call = SimpleNamespace(
            employee_id=uuid4(),
            workspace_id=uuid4(),
            captured_fields={
                "employee_brief": "Your name is maya for V Farms Resort.",
                "employee_language": "Telugu",
                "employee_website_knowledge": "V-Farms Medchal farm stays. Book cottages.",
                "knowledge_state": "published",
                "employee_snapshot_revision": "3",
                "conversation_language": "te-IN",
                "inbound_chat": {"turns": []},
            },
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        db = MagicMock()
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ), patch(
            "app.services.voice.inbound_llm_engine.generate_inbound_llm_turn",
            return_value=__import__(
                "app.services.voice.voice_llm_router", fromlist=["LlmTurnResult"]
            ).LlmTurnResult(
                "22వ తారీఖు booking కోసం check-in తేదీ confirm చేస్తే చూస్తాను అండి.",
                40.0,
                "mock",
            ),
        ):
            reply, _ = process_inbound_speech(
                db,
                call,
                caller_text="V-Forms resort book 22nd",
                stt_language="te-IN",
            )
        low = reply.lower()
        self.assertNotIn("college", low)
        self.assertNotIn("computer science", low)
        self.assertNotIn("anitha", low)
        self.assertNotEqual(call.captured_fields.get("speech_stack"), "sarvam-m05")

    def test_team_employee_blocks_m05(self) -> None:
        from app.services.voice.m05_sarvam import m05_voice_enabled, team_employee_voice_active

        maya = {
            "employee_brief": "Your name is maya for V Farms Resort.",
            "employee_website_knowledge": "V-Farms near Medchal farm stays.",
            "knowledge_state": "published",
            "employee_snapshot_revision": "12",
        }
        self.assertTrue(team_employee_voice_active(maya))
        self.assertFalse(m05_voice_enabled(call_fields=maya))


if __name__ == "__main__":
    unittest.main()