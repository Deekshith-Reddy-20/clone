"""
import os
import unittest
_LEGACY = os.getenv("RUN_LEGACY_FASTPATH") != "1"
def _skip_legacy(reason="legacy fast-path"): pass

Regression: Telugu 22→25 booking loop (text through process_inbound_speech).

First failure before fix: turn 3 "25th తేదీ" wrote checkout day into check_in
because merge_utterance ignored last_prompt=check_out.
"""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.voice.booking_state import dump_booking, load_booking
from app.services.voice.inbound_conversation import process_inbound_speech


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, _call) -> None:
        pass


def _call() -> SimpleNamespace:
    return SimpleNamespace(
        captured_fields={
            "employee_brief": "Resort booking",
            "employee_language": "Telugu",
            "employee_website_knowledge": "Rooms on request.",
            "inbound_chat": {"turns": []},
        },
        transcript="",
        summary="",
        outcome=None,
        finalized_at=None,
        duration_seconds=0,
    )


LOOP_TRANSCRIPT = [
    "నాకు 22వ తేదీ booking availability వచ్చింది.",
    "check-in తేదీ 22",
    "25th తేదీ",
    "ఏం విషయం చెప్పాలి?",
    "25 డేజి.",
    "ఏం చెప్పాలి?",
    "Check-in తేదీ 21.",
]

NATURAL_TRANSCRIPT = [
    "నాకు 22వ తేదీ booking availability వచ్చింది.",
    "check-in తేదీ 22",
    "25th తేదీ",
    "నవంబర్",
    "మొత్తం 4 మంది",
]


@skip_unless_legacy
class BookingLoopRegression(unittest.TestCase):
    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_exact_loop_transcript(self, _sarvam) -> None:
        call = _call()
        db = _FakeSession()
        replies: list[str] = []
        for text in LOOP_TRANSCRIPT:
            r, _ = process_inbound_speech(db, call, caller_text=text, stt_language="te-IN")
            replies.append(r)
        st = load_booking(call.captured_fields)
        for r in replies:
            self.assertNotIn("మరో విషయం", r)
        self.assertEqual(st.check_in_day, 21)
        self.assertEqual(st.check_out_day, 25)
        self.assertIn("22న", replies[0])
        self.assertIn("చెక్-ఔట్", replies[1])
        self.assertIn("నెల", replies[2])
        self.assertIn("22", replies[3])
        self.assertIn("25", replies[3])
        self.assertIn("రోజులు", replies[4])
        self.assertTrue("21" in replies[6] or "నెల" in replies[6])

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_natural_fixed_conversation(self, _sarvam) -> None:
        call = _call()
        db = _FakeSession()
        for text in NATURAL_TRANSCRIPT:
            process_inbound_speech(db, call, caller_text=text, stt_language="te-IN")
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in_day, 22)
        self.assertEqual(st.check_out_day, 25)
        self.assertTrue(st.month_confirmed)
        self.assertEqual(st.guest_count, 4)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_month_step_single_day_corrects_check_in(self, _sarvam) -> None:
        call = _call()
        db = _FakeSession()
        for line in ["check-in 22", "25th తేదీ"]:
            process_inbound_speech(db, call, caller_text=line, stt_language="te-IN")
        st = load_booking(call.captured_fields)
        st.last_prompt = "month"
        call.captured_fields["inbound_booking"] = dump_booking(st)
        process_inbound_speech(db, call, caller_text="21వ తేదీ", stt_language="te-IN")
        st2 = load_booking(call.captured_fields)
        self.assertEqual(st2.check_in_day, 21)
        self.assertEqual(st2.check_out_day, 25)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_fifth_date_turn_and_explicit_checkin_correction(self, _sarvam) -> None:
        call = _call()
        db = _FakeSession()
        for line in [
            "22వ తేదీ check in.",
            "ఇరవై ఐదో తేదీ",
            "పూల్ ఎన్ని గంటల వరకు ఓపెన్",
            "లేదు, చెక్-ఇన్ ఇరవై ఒకటి",
        ]:
            process_inbound_speech(db, call, caller_text=line, stt_language="te-IN")
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in_day, 21)
        self.assertEqual(st.check_out_day, 25)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_bare_negation_leaves_dates(self, _sarvam) -> None:
        call = _call()
        db = _FakeSession()
        for line in ["check-in తేదీ 22", "25th తేదీ"]:
            process_inbound_speech(db, call, caller_text=line, stt_language="te-IN")
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in_day, 22)
        self.assertEqual(st.check_out_day, 25)
        reply, _, _ = __import__(
            "app.services.voice.inbound_booking", fromlist=["try_booking_turn"]
        ).try_booking_turn(
            caller_text="లేదు",
            lang="te-IN",
            fields=call.captured_fields,
            website_knowledge="",
        )
        self.assertTrue("ఏ తేదీ" in (reply or "") or "కొత్త చెక్-ఇన్" in (reply or ""))
        st2 = load_booking(call.captured_fields)
        self.assertEqual(st2.check_in_day, 22)
        self.assertEqual(st2.check_out_day, 25)


if __name__ == "__main__":
    unittest.main()