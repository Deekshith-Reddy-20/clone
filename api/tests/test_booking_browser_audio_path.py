"""Worker route: ExotelVoicebotSession._handle_caller_text → process_inbound_speech (no LLM mock)."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import Call
from app.services.voice.booking_state import load_booking
from app.services.voice.exotel_voicebot_session import ExotelVoicebotSession


class MockExotelWS:
    async def receive_text(self) -> str:
        raise asyncio.CancelledError()

    async def send_json(self, _data: dict) -> None:
        pass


class BookingWorkerPath(unittest.TestCase):
    def test_worker_turns_persist_booking_days(self) -> None:
        async def _run() -> None:
            call_id = uuid.uuid4()
            session = ExotelVoicebotSession(MockExotelWS(), call_id)
            session.stream_sid = "browser-test"
            session._browser_preview = True
            session._greeting_done = True
            session.lang_code = "te-IN"

            call = SimpleNamespace(
                captured_fields={
                    "employee_brief": "Resort",
                    "employee_language": "Telugu",
                    "employee_website_knowledge": "Rooms.",
                    "browser_preview": True,
                    "inbound_chat": {"turns": []},
                },
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

            phrases = [
                "check-in తేదీ 22",
                "25th తేదీ",
                "Check-in తేదీ 21.",
            ]
            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
                patch(
                    "app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice",
                    return_value=True,
                ),
                patch.object(ExotelVoicebotSession, "_speak", new_callable=AsyncMock),
            ):
                for p in phrases:
                    await session._handle_caller_text(p, stt_language="te-IN")
            st = load_booking(call.captured_fields)
            self.assertEqual(st.check_in_day, 21)
            self.assertEqual(st.check_out_day, 25)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()