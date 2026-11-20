"""
import os
import unittest
_LEGACY = os.getenv("RUN_LEGACY_FASTPATH") != "1"
def _skip_legacy(reason="legacy fast-path"): pass

Release-blocking voice benchmark (text + worker path).

Same handler as browser: POST voice-preview → ws /v1/ws/exotel/voice/{call_id}
→ ExotelVoicebotSession → process_inbound_speech → try_booking_turn.

The old failure (25th after checkout ask → మరో విషయం loop) came from
merge_utterance assigning bare days to check-in and avoid_repeat_reply on
identical checkout prompts — not from Sarvam STT.
"""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import Call
from app.services.voice.booking_state import load_booking
from app.services.voice.exotel_voicebot_session import ExotelVoicebotSession
from app.services.voice.inbound_conversation import process_inbound_speech


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, _call) -> None:
        pass


def _base_fields() -> dict:
    return {
        "employee_brief": "Resort stay assistant — short spoken Telugu.",
        "employee_language": "Telugu",
        "employee_website_knowledge": "Pool opens 8:30 AM. Closes 10 PM.",
        "employee_natural_spoken": True,
        "browser_preview": True,
        "inbound_chat": {"turns": []},
    }


@skip_unless_legacy
class LiveVoiceBenchmark(unittest.TestCase):
    CORE_TURNS = [
        "check-in తేదీ 22",
        "25th తేదీ",
        "Check-in తేదీ 21.",
    ]

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_core_checkout_turn_never_generic_fallback(self, _sarvam) -> None:
        call = SimpleNamespace(
            captured_fields=dict(_base_fields()),
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        db = _FakeSession()
        replies: list[str] = []
        for text in self.CORE_TURNS:
            r, _ = process_inbound_speech(db, call, caller_text=text, stt_language="te-IN")
            replies.append(r)
        for r in replies:
            self.assertNotIn("మరో విషయం ఏదైనా", r)
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in_day, 21)
        self.assertEqual(st.check_out_day, 25)
        self.assertIn("25", replies[1])
        self.assertIn("నెల", replies[1])

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_release_blocking_telugu_session(self, _sarvam) -> None:
        call = SimpleNamespace(
            captured_fields=dict(_base_fields()),
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        db = _FakeSession()
        script = [
            "నాకు 22వ తేదీ availability ఉందా?",
            "check-in తేదీ 22",
            "25th తేదీ",
            "మీ pool timings",
            "ఇంకా స్టే కావాలి",
            "Check-in తేదీ 21.",
            "నవంబర్",
            "4 మంది",
        ]
        for text in script:
            r, _ = process_inbound_speech(db, call, caller_text=text, stt_language="te-IN")
            self.assertNotIn("మరో విషయం ఏదైనా", r)
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in_day, 21)
        self.assertEqual(st.check_out_day, 25)
        self.assertEqual(st.guest_count, 4)
        self.assertTrue(st.month_confirmed)

    def test_spoken_telugu_ordinal_checkout_day(self) -> None:
        call = SimpleNamespace(
            captured_fields=dict(_base_fields()),
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        db = _FakeSession()
        with patch(
            "app.services.voice.inbound_conversation.use_sarvam_inbound_voice",
            return_value=True,
        ):
            process_inbound_speech(db, call, caller_text="check-in తేదీ 22", stt_language="te-IN")
            process_inbound_speech(
                db,
                call,
                caller_text="ఇరవై ఐదో తేదీ",
                stt_language="te-IN",
            )
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_out_day, 25)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_correction_ledu_checkin_21(self, _sarvam) -> None:
        call = SimpleNamespace(
            captured_fields=dict(_base_fields()),
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        db = _FakeSession()
        for text in ("check-in తేదీ 22", "25th తేదీ"):
            process_inbound_speech(db, call, caller_text=text, stt_language="te-IN")
        r, _ = process_inbound_speech(
            db,
            call,
            caller_text="లేదు, చెక్-ఇన్ 21.",
            stt_language="te-IN",
        )
        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in_day, 21)
        self.assertEqual(st.check_out_day, 25)
        self.assertNotIn("మరో విషయం", r)

    def test_worker_path_same_handler_as_browser(self) -> None:
        async def _run() -> None:
            session = ExotelVoicebotSession(MagicMock(), uuid.uuid4())
            session._browser_preview = True
            session._greeting_done = True
            session.lang_code = "te-IN"
            call = SimpleNamespace(
                captured_fields=dict(_base_fields()),
                transcript="",
                summary="",
                outcome=None,
                finalized_at=None,
                duration_seconds=0,
            )

            def session_local():
                db = MagicMock()
                db.get.return_value = call
                db.commit = MagicMock()
                db.close = MagicMock()
                db.refresh = MagicMock()
                return db

            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
                patch(
                    "app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice",
                    return_value=True,
                ),
                patch.object(ExotelVoicebotSession, "_speak", new_callable=AsyncMock),
            ):
                for phrase in self.CORE_TURNS:
                    await session._handle_caller_text(phrase, stt_language="te-IN")
            st = load_booking(call.captured_fields)
            self.assertEqual((st.check_in_day, st.check_out_day), (21, 25))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()