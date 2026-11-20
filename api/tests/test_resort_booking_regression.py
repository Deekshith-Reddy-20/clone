"""Resort Telugu booking + pool side questions — text replay through process_inbound_speech."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.voice.booking_state import load_booking
from app.services.voice.inbound_conversation import process_inbound_speech


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
class ResortBookingRegression(unittest.TestCase):
    KNOWLEDGE = "Swimming pool opens daily at 8:30 AM. Closes at 10 PM."

    def setUp(self) -> None:
        self.base = {
            "employee_brief": "V Farms Resort booking assistant.",
            "employee_language": "Telugu",
            "employee_website_knowledge": self.KNOWLEDGE,
            "employee_natural_spoken": True,
            "inbound_chat": {"turns": []},
        }
        self.db = _FakeSession()

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_unfinished_then_availability_not_generic_reset(self, _sarvam) -> None:
        call = _call(self.base)
        r1, _ = process_inbound_speech(
            self.db,
            call,
            caller_text="నాకు మీ resort-లో ఎల్లుండి…",
            stt_language="te-IN",
        )
        self.assertIn("పూర్తి", r1)

        r2, _ = process_inbound_speech(
            self.db,
            call,
            caller_text="1st తారీకు availability",
            stt_language="te-IN",
        )
        self.assertNotIn("మరో విషయం", r2)
        self.assertTrue("తేదీ" in r2 or "చెక్" in r2 or "నెల" in r2)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_pool_timings_telugu_not_english_snippet(self, _sarvam) -> None:
        call = _call(self.base)
        reply, _ = process_inbound_speech(
            self.db,
            call,
            caller_text="మీ pool timings",
            stt_language="te-IN",
        )
        self.assertIn("8:30", reply)
        self.assertIn("పూల్", reply)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_dates_guests_month_and_confusion_recap(self, _sarvam) -> None:
        call = _call(self.base)
        process_inbound_speech(
            self.db, call, caller_text="అవైలబిలిటీ ఉందా?", stt_language="te-IN"
        )
        process_inbound_speech(self.db, call, caller_text="26 నుంచి 28", stt_language="te-IN")
        r_guests, _ = process_inbound_speech(
            self.db, call, caller_text="30 మంది", stt_language="te-IN"
        )
        st = load_booking(call.captured_fields)
        self.assertEqual(st.guest_count, 30)
        self.assertIsNotNone(st.check_in)
        self.assertIsNotNone(st.check_out)
        self.assertNotIn("చెక్-ఔట్", r_guests)

        r_confuse, _ = process_inbound_speech(
            self.db, call, caller_text="ఏం చెప్పాలి?", stt_language="te-IN"
        )
        self.assertIn("30", r_confuse)
        self.assertNotIn("మరో విషయం", r_confuse)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_lone_8_does_not_wipe_checkout_28(self, _sarvam) -> None:
        call = _call(self.base)
        fields = call.captured_fields
        fields["inbound_booking"] = {
            "check_in": "2026-11-26",
            "check_out": "2026-11-28",
            "guest_count": 30,
            "day_only_range": True,
            "month_confirmed": True,
        }
        reply, _ = process_inbound_speech(self.db, call, caller_text="8", stt_language="te-IN")
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_out, "2026-11-28")
        self.assertTrue("8" in reply or "ఎనిమిద" in reply or "అవుట్" in reply)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_pool_during_active_booking_keeps_state(self, _sarvam) -> None:
        call = _call(self.base)
        call.captured_fields["inbound_booking"] = {
            "check_in": "2026-11-26",
            "check_out": "2026-11-28",
            "guest_count": 30,
        }
        reply, _ = process_inbound_speech(
            self.db,
            call,
            caller_text="మీ pool timings",
            stt_language="te-IN",
        )
        self.assertIn("పూల్", reply)
        st = load_booking(call.captured_fields)
        self.assertEqual(st.guest_count, 30)
        self.assertEqual(st.check_out, "2026-11-28")


if __name__ == "__main__":
    unittest.main()