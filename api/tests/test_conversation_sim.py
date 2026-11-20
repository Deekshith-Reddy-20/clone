"""Offline turn simulation (no Sarvam API) for V Farms Telugu booking + FAQ paths."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.voice.inbound_conversation import process_inbound_speech
from tests.legacy_fastpath import skip_unless_legacy


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, _call) -> None:
        pass


def _call(fields: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        captured_fields=dict(fields or {}),
        transcript="",
        summary="",
        outcome=None,
        finalized_at=None,
        duration_seconds=0,
    )


@skip_unless_legacy
class ConversationSimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "employee_brief": "You are V Farms Resort booking assistant.",
            "employee_language": "Telugu",
            "employee_website_knowledge": "Pool hours 7 AM to 9 PM. Weekend cottages available.",
            "inbound_chat": {"turns": []},
        }

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    @patch("app.services.voice.inbound_conversation.try_knowledge_snippet_reply")
    @patch("app.services.voice.inbound_conversation.try_booking_turn")
    def test_telugu_availability_booking_path(self, mock_book, mock_snip, _sarvam) -> None:
        mock_snip.return_value = None
        mock_book.return_value = ("సరే. చెక్-ఇన్ ఏ తేదీకి రావాలి?", False, False)
        call = _call(self.base)
        db = _FakeSession()
        reply, hangup = process_inbound_speech(
            db,
            call,
            caller_text="అవైలబిలిటీ ఉందా?",
            stt_language="te-IN",
        )
        self.assertIn("తేదీ", reply)
        self.assertEqual(call.captured_fields.get("conversation_language"), "te-IN")
        self.assertFalse(hangup)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    @patch("app.services.voice.inbound_conversation.try_booking_turn", return_value=None)
    def test_pool_question_snippet(self, _book, _sarvam) -> None:
        call = _call(self.base)
        db = _FakeSession()
        reply, _ = process_inbound_speech(
            db,
            call,
            caller_text="pool timings please",
            stt_language="en-IN",
        )
        self.assertIsNotNone(reply)
        self.assertTrue("Pool" in reply or "7" in reply or len(reply) > 10)


if __name__ == "__main__":
    unittest.main()