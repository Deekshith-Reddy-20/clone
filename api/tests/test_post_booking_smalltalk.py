"""After booking is confirmed, answer name, resort, and location — not repeat confirm."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.voice.booking_state import load_booking
from app.services.voice.employee_playbook import agent_name_from_brief, try_reception_smalltalk_reply
from app.services.voice.inbound_conversation import process_inbound_speech


class _DB:
    def commit(self) -> None:
        pass

    def refresh(self, _c) -> None:
        pass


def _call() -> SimpleNamespace:
    return SimpleNamespace(
        captured_fields={
            "employee_brief": "Your name is Maya for V Farms Resort near Medchal.",
            "employee_language": "Telugu",
            "employee_website_knowledge": (
                "V-Farms Resort cottages near Medchal highway. Weekend farm stays."
            ),
            "conversation_language": "te-IN",
            "inbound_chat": {"turns": []},
        },
        transcript="",
        summary="",
        outcome=None,
        finalized_at=None,
        duration_seconds=0,
    )


@skip_unless_legacy
class PostBookingSmalltalkTests(unittest.TestCase):
    def test_agent_name_from_brief(self) -> None:
        self.assertEqual(
            agent_name_from_brief("Your name is Maya for V Farms Resort."),
            "Maya",
        )

    def test_smalltalk_replies(self) -> None:
        know = "V-Farms near Medchal highway."
        brief = "Your name is Maya for V Farms Resort."
        r1 = try_reception_smalltalk_reply("నీ పేరేం పేరు?", brief=brief, website_knowledge=know, lang="te-IN")
        self.assertIsNotNone(r1)
        self.assertIn("Maya", r1)
        self.assertNotIn("కన్ఫర్మ్", r1)

        r2 = try_reception_smalltalk_reply("మీ resort పేరు ఏం?", brief=brief, website_knowledge=know, lang="te-IN")
        self.assertIsNotNone(r2)
        self.assertIn("V Farms", r2)

        r3 = try_reception_smalltalk_reply("మీ current location చెప్పగలవా?", brief=brief, website_knowledge=know, lang="te-IN")
        self.assertIsNotNone(r3)
        self.assertTrue("Medchal" in r3 or "మెద్చల్" in r3)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_after_confirm_answers_identity_not_repeat(self, _sarvam) -> None:
        call = _call()
        db = _DB()
        script = [
            "నవంబర్ 22 నుంచి 25, 40 మంది",
            "book చేయండి",
            "నీ పేరేం?",
            "మీ resort పేరు?",
            "current location చెప్పండి",
        ]
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            for line in script:
                reply, _ = process_inbound_speech(db, call, caller_text=line, stt_language="te-IN")
            st = load_booking(call.captured_fields)
            self.assertTrue(st.booking_ref)
            self.assertIn("Maya", reply)
            self.assertNotIn("మళ్ళీ చెప్తాను", reply)
            self.assertNotIn("రిఫరెన్స్ VF-", reply[-80:] if len(reply) > 80 else reply)
        # Last reply should be location-ish
        self.assertTrue("Medchal" in reply or "మెద్చల్" in reply or "property" in reply)


if __name__ == "__main__":
    unittest.main()