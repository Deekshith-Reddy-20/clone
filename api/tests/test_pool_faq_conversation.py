"""Pool FAQ: documented opening time + missing heated-pool detail."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
import uuid
from unittest.mock import MagicMock

from app.models import Call
from app.services.voice.call_turn_policy import reject_turn_reason
from app.services.voice.employee_playbook import try_knowledge_missing_reply, try_knowledge_snippet_reply
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.sarvam import is_hindi_ack_noise, resolve_call_language


@skip_unless_legacy
class PoolFaqTests(unittest.TestCase):
    KNOWLEDGE = "Swimming pool opens daily at 8:30 AM. Closes at 10 PM."
    KNOWLEDGE_V2 = "Swimming pool opens daily at 6:00 AM. Closes at 9 PM."

    def test_hindi_ack_rejected_on_telugu_line(self) -> None:
        sample = "हाँ जी हाँ जी हाँ जी"
        self.assertTrue(is_hindi_ack_noise(sample))
        reason = reject_turn_reason(
            sample,
            employee_language="Telugu",
            conversation_language="hi-IN",
        )
        self.assertIn(reason, ("hindi_ack_noise", "hindi_noise_telugu_line", "spurious"))

    def test_lang_stays_telugu_after_polluted_conv(self) -> None:
        lang = resolve_call_language(
            caller_text="పూల్ పొద్దున ఎన్ని గంటలకు తెరుస్తారు?",
            conversation_language="hi-IN",
            employee_language="Telugu",
            stt_language="hi-IN",
        )
        self.assertEqual(lang, "te-IN")

    def test_snippet_pool_time(self) -> None:
        reply = try_knowledge_snippet_reply(
            "పూల్ పొద్దున ఎన్ని గంటలకు తెరుస్తారు?",
            brief="Resort desk",
            website_knowledge=self.KNOWLEDGE,
            lang="te-IN",
        )
        self.assertIsNotNone(reply)
        self.assertIn("8:30", reply)
        v2 = try_knowledge_snippet_reply(
            "What time does the pool open?",
            brief="Resort desk",
            website_knowledge=self.KNOWLEDGE_V2,
            lang="en-IN",
        )
        self.assertIsNotNone(v2)
        self.assertIn("6:00", v2)

    def test_heated_pool_not_in_doc(self) -> None:
        reply = try_knowledge_missing_reply(
            "అది హీటెడ్ పూలా?",
            website_knowledge=self.KNOWLEDGE,
            lang="te-IN",
        )
        self.assertIsNotNone(reply)
        self.assertIn("లేవండి", reply)

    def test_two_turn_inbound_speech(self) -> None:
        call = MagicMock(spec=Call)
        call.captured_fields = {
            "employee_brief": "Resort",
            "employee_language": "Telugu",
            "employee_website_knowledge": self.KNOWLEDGE,
            "employee_natural_spoken": True,
            "conversation_language": "te-IN",
            "inbound_chat": {"turns": []},
        }
        call.transcript = ""
        call.summary = ""
        call.duration_seconds = 0
        call.outcome = None
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        q1 = "పూల్ పొద్దున ఎన్ని గంటలకు తెరుస్తారు?"
        r1, _ = process_inbound_speech(db, call, caller_text=q1, stt_language="te-IN")
        self.assertIn("8:30", r1)

        q2 = "అది హీటెడ్ పూలా?"
        r2, _ = process_inbound_speech(db, call, caller_text=q2, stt_language="te-IN")
        self.assertIn("లేవండి", r2)
        turns = call.captured_fields["inbound_chat"]["turns"]
        self.assertEqual(len(turns), 4)


if __name__ == "__main__":
    unittest.main()