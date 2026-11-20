"""Exotel WebSocket session: pre-roll during playback + multi-turn (mocked Sarvam)."""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import math
import struct
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import Call
from app.services.voice.exotel_voicebot_session import (
    CHUNK_PCM,
    MARK_GREETING_PLAYBACK,
    ExotelVoicebotSession,
    MIN_SPEECH_BYTES,
)


def _speech_pcm(duration_s: float = 1.2, hz: float = 220.0, amp: int = 4500) -> bytes:
    n = int(8000 * duration_s)
    out = bytearray()
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * hz * i / 8000))
        out += struct.pack("<h", v)
    return bytes(out)


def _pcm_to_lin16_chunks(pcm: bytes, chunk_bytes: int = CHUNK_PCM) -> list[str]:
    chunks: list[str] = []
    for i in range(0, len(pcm), chunk_bytes):
        piece = pcm[i : i + chunk_bytes]
        if len(piece) < 2:
            continue
        chunks.append(base64.b64encode(piece).decode("ascii"))
    return chunks


def _pcm_to_mulaw_chunks(pcm: bytes, chunk_samples: int = 160) -> list[str]:
    """20 ms @ 8 kHz → 160 samples → 320-byte PCM16 chunks (typical Exotel pacing)."""
    chunks: list[str] = []
    step = chunk_samples * 2
    for i in range(0, len(pcm), step):
        piece = pcm[i : i + step]
        if len(piece) < 2:
            continue
        ulaw = audioop.lin2ulaw(piece, 2)
        chunks.append(base64.b64encode(ulaw).decode("ascii"))
    return chunks


def _media_msg(payload_b64: str, stream_sid: str = "st-test") -> dict:
    return {
        "event": "media",
        "stream_sid": stream_sid,
        "media": {"track": "inbound", "payload": payload_b64},
    }


class MockExotelWS:
    def __init__(self) -> None:
        self._in: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []
        self._closed = False

    def feed(self, msg: dict) -> None:
        self._in.put_nowait(json.dumps(msg))

    async def receive_text(self) -> str:
        return await self._in.get()

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _fake_db_call() -> Call:
    call = MagicMock(spec=Call)
    call.captured_fields = {
        "employee_brief": "V Farms resort assistant.",
        "employee_language": "Telugu",
        "employee_website_knowledge": "Pool 7 AM to 9 PM.",
        "inbound_chat": {"turns": []},
        "conversation_language": "te-IN",
    }
    return call


class TestIngressMediaFormat(unittest.TestCase):
    def test_base64_encoding_defaults_to_slin_8k(self) -> None:
        enc, rate = ExotelVoicebotSession._ingress_from_media_format({"encoding": "base64"})
        self.assertEqual(enc, "linear16")
        self.assertEqual(rate, 8000)

    def test_mulaw_encoding(self) -> None:
        enc, rate = ExotelVoicebotSession._ingress_from_media_format(
            {"encoding": "audio/x-mulaw;rate=8000"}
        )
        self.assertEqual(enc, "mulaw")
        self.assertEqual(rate, 8000)


class TestPlaybackGuard(unittest.TestCase):
    def test_playback_guard_covers_long_greeting(self) -> None:
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, uuid.uuid4())
        play_s = 5.0
        n_chunks = 50
        guard = session._playback_guard_seconds(play_s, n_chunks)
        self.assertGreaterEqual(guard, 1.0, "listen gate must stay closed through PSTN playout")


class TestPreRollBuffer(unittest.TestCase):
    def test_pre_roll_merge_keeps_tail_only(self) -> None:
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, uuid.uuid4())
        session.stream_sid = "s"
        session._pre_roll.extend(b"\x00" * 20_000)
        session._pre_roll.extend(b"\xff\xff" * 10_000)
        session._playback_until = 0.0
        session._merge_pre_roll_into_buffer()
        self.assertEqual(len(session._pre_roll), 0)
        self.assertLessEqual(len(session.pcm_buffer), 16_000 + 100)
        self.assertGreaterEqual(len(session.pcm_buffer), 10_000)

    def test_pre_roll_merges_after_playback(self) -> None:
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, uuid.uuid4())
        session.stream_sid = "s"
        session._playback_until = time.monotonic() + 2.0
        pcm = _speech_pcm(0.8)
        session._ingest_inbound_pcm(pcm)
        self.assertGreaterEqual(len(session._pre_roll), len(pcm) - 10)
        self.assertEqual(len(session.pcm_buffer), 0)
        session._playback_until = 0.0
        session._ignore_input_until = 0.0
        session._merge_pre_roll_into_buffer()
        self.assertGreaterEqual(len(session.pcm_buffer), MIN_SPEECH_BYTES)


class ExotelVoicebotWSAsync(unittest.IsolatedAsyncioTestCase):
    async def _run_two_turn_mock(self) -> tuple[int, int]:
        call_id = uuid.uuid4()
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, call_id)
        fake_call = _fake_db_call()

        def session_local():
            db = MagicMock()
            db.get.return_value = fake_call
            db.commit = MagicMock()
            db.close = MagicMock()
            db.refresh = MagicMock()
            return db

        tts_pcm = b"\x01\x00" * (CHUNK_PCM * 4)

        async def fast_speak(
            self: ExotelVoicebotSession, text: str, *, playback_mark: str = ""
        ) -> None:
            self.speaking = True
            await self._send_wire_audio(tts_pcm[:CHUNK_PCM])
            self.speaking = False
            play_s = len(tts_pcm) / 16000.0
            self._playback_until = time.monotonic() + play_s + 0.05
            self._ignore_input_until = self._playback_until
            if playback_mark:
                await self._handle_playback_mark(playback_mark, source="test")

        stt_calls: list[int] = []

        def fake_transcribe(buf: bytes, *, hint_language: str = "") -> tuple[str, str]:
            stt_calls.append(len(buf))
            if len(stt_calls) == 1:
                return "ఈ వీకెండ్ గదులు ఉన్నాయా?", "te-IN"
            return "నాకు ఈరోజు రేటు ఎంత?", "te-IN"

        async def run_session() -> None:
            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
                patch(
                    "app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice",
                    return_value=True,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_tts_pcm_8k",
                    return_value=tts_pcm,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_transcribe_pcm",
                    side_effect=fake_transcribe,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.process_inbound_speech",
                    side_effect=[
                        ("మీరు అడిగిన వీకెండ్ కి గదులు ఉన్నాయి.", False),
                        ("రేటు వెబ్ సైట్ లో ఉంది.", False),
                    ],
                ),
                patch.object(ExotelVoicebotSession, "_speak", fast_speak),
                patch.object(ExotelVoicebotSession, "_emit_call_trace", new_callable=AsyncMock),
            ):
                await session.run()

        runner = asyncio.create_task(run_session())

        ws.feed({"event": "connected"})
        ws.feed(
            {
                "event": "start",
                "stream_sid": "st-test",
                "start": {"mediaFormat": {"encoding": "audio/x-mulaw"}},
            }
        )
        await asyncio.sleep(0.05)

        async def feed_utterance() -> None:
            pcm = _speech_pcm(1.4)
            for payload in _pcm_to_mulaw_chunks(pcm):
                ws.feed(_media_msg(payload))
                await asyncio.sleep(0.02)

        await feed_utterance()
        await asyncio.sleep(3.2)
        await feed_utterance()
        await asyncio.sleep(3.5)
        ws.feed({"event": "stop"})
        await asyncio.wait_for(runner, timeout=8.0)

        outbound_pcm = [
            s
            for s in ws.sent
            if s.get("event") == "media" and s.get("media", {}).get("payload")
        ]
        return len(stt_calls), len(outbound_pcm)

    async def test_speech_during_greeting_playback_gets_answer(self) -> None:
        stt_n, media_n = await self._run_two_turn_mock()
        self.assertGreaterEqual(stt_n, 1, "STT should run after pre-roll merge")
        self.assertGreaterEqual(media_n, 2, "greeting + at least one answer outbound media")

    async def test_two_consecutive_questions_same_session(self) -> None:
        stt_n, media_n = await self._run_two_turn_mock()
        self.assertGreaterEqual(stt_n, 2, "two accepted STT turns in one session")
        self.assertGreaterEqual(media_n, 3, "greeting plus two answer playbacks")

    async def test_hindi_echo_does_not_flip_telugu_session(self) -> None:
        call_id = uuid.uuid4()
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, call_id)
        fake_call = _fake_db_call()

        def session_local():
            db = MagicMock()
            db.get.return_value = fake_call
            db.commit = MagicMock()
            db.close = MagicMock()
            db.refresh = MagicMock()
            return db

        stt_calls: list[str] = []

        def fake_transcribe(buf: bytes, *, hint_language: str = "") -> tuple[str, str]:
            n = len(stt_calls)
            stt_calls.append("x")
            if n == 0:
                return "हाँ जी हाँ जी", "hi-IN"
            return "పూల్ పొద్దున ఎన్ని గంటలకు తెరుస్తారు?", "te-IN"

        tts_pcm = b"\x01\x00" * (CHUNK_PCM * 4)

        async def fast_speak(
            self: ExotelVoicebotSession, text: str, *, playback_mark: str = ""
        ) -> None:
            self.speaking = True
            await self._send_wire_audio(tts_pcm[:CHUNK_PCM])
            self.speaking = False
            play_s = len(tts_pcm) / 16000.0
            self._playback_until = time.monotonic() + play_s + 0.2
            self._ignore_input_until = self._playback_until
            if playback_mark:
                await self._handle_playback_mark(playback_mark, source="test")

        async def run_session() -> None:
            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
                patch("app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice", return_value=True),
                patch("app.services.voice.exotel_voicebot_session.sarvam_tts_pcm_8k", return_value=tts_pcm),
                patch("app.services.voice.exotel_voicebot_session.sarvam_transcribe_pcm", side_effect=fake_transcribe),
                patch(
                    "app.services.voice.exotel_voicebot_session.process_inbound_speech",
                    return_value=("పూల్ ఉదయం 7 గంటలకు తెరుచుకుంటుంది.", False),
                ),
                patch.object(ExotelVoicebotSession, "_speak", fast_speak),
                patch.object(ExotelVoicebotSession, "_emit_call_trace", new_callable=AsyncMock),
            ):
                await session.run()

        runner = asyncio.create_task(run_session())
        ws.feed({"event": "connected"})
        ws.feed(
            {
                "event": "start",
                "stream_sid": "st-test",
                "start": {"mediaFormat": {"encoding": "audio/x-mulaw"}},
            }
        )
        await asyncio.sleep(0.1)
        for _ in range(2):
            pcm = _speech_pcm(1.3)
            for payload in _pcm_to_mulaw_chunks(pcm):
                ws.feed(_media_msg(payload))
                await asyncio.sleep(0.02)
            await asyncio.sleep(3.0)
        ws.feed({"event": "stop"})
        await asyncio.wait_for(runner, timeout=12.0)
        self.assertEqual(session.lang_code, "te-IN")
        self.assertEqual(len(stt_calls), 2)

    async def test_pstn_linear16_two_questions_after_greeting(self) -> None:
        """Mirrors live Exotel: slin @ 8kHz (encoding hint base64), media during + after welcome."""
        call_id = uuid.uuid4()
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, call_id)
        fake_call = _fake_db_call()
        tts_pcm = b"\x02\x00" * (CHUNK_PCM * 6)

        def session_local():
            db = MagicMock()
            db.get.return_value = fake_call
            db.commit = MagicMock()
            db.close = MagicMock()
            db.refresh = MagicMock()
            return db

        stt_calls: list[int] = []

        def fake_transcribe(buf: bytes, *, hint_language: str = "") -> tuple[str, str]:
            stt_calls.append(len(buf))
            if len(stt_calls) == 1:
                return "OPD టైమింగ్స్ ఎంటి?", "te-IN"
            return "అపాయింట్మెంట్ ఎలా తీసుకోవాలి?", "te-IN"

        async def fast_speak(
            self: ExotelVoicebotSession, text: str, *, playback_mark: str = ""
        ) -> None:
            self.speaking = True
            await self._send_wire_audio(tts_pcm[:CHUNK_PCM])
            self.speaking = False
            play_s = len(tts_pcm) / 16000.0
            self._playback_until = time.monotonic() + play_s + 0.05
            self._ignore_input_until = self._playback_until
            if playback_mark:
                await self._handle_playback_mark(playback_mark, source="test")

        async def run_session() -> None:
            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
                patch(
                    "app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice",
                    return_value=True,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_tts_pcm_8k",
                    return_value=tts_pcm,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_transcribe_pcm",
                    side_effect=fake_transcribe,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.process_inbound_speech",
                    side_effect=[
                        ("OPD ఉదయం 9 నుంచి సాయంత్రం 5 వరకు.", False),
                        ("వెబ్‌సైట్ లేదా ఈ నంబర్ ద్వారా అపాయింట్మెంట్ తీసుకోండి.", False),
                    ],
                ),
                patch.object(ExotelVoicebotSession, "_speak", fast_speak),
                patch.object(ExotelVoicebotSession, "_emit_call_trace", new_callable=AsyncMock),
            ):
                await session.run()

        runner = asyncio.create_task(run_session())
        ws.feed({"event": "connected"})
        ws.feed(
            {
                "event": "start",
                "stream_sid": "pstn-live",
                "start": {"mediaFormat": {"encoding": "base64", "sampleRate": 8000}},
            }
        )
        await asyncio.sleep(0.05)

        async def feed_utterance() -> None:
            pcm = _speech_pcm(1.5, amp=5200)
            for payload in _pcm_to_lin16_chunks(pcm):
                ws.feed(_media_msg(payload, stream_sid="pstn-live"))
                await asyncio.sleep(0.02)

        await feed_utterance()
        await asyncio.sleep(5.0)
        await feed_utterance()
        await asyncio.sleep(3.5)
        ws.feed({"event": "stop"})
        await asyncio.wait_for(runner, timeout=25.0)
        self.assertGreaterEqual(len(stt_calls), 2, "two STT finals after PSTN-style greeting")
        outbound = [s for s in ws.sent if s.get("event") == "media"]
        self.assertGreaterEqual(len(outbound), 3, "greeting + two replies")

    async def test_real_speak_playback_gate_allows_post_greeting_stt(self) -> None:
        """Uses production _speak playback guard (mocked Sarvam PCM only)."""
        call_id = uuid.uuid4()
        ws = MockExotelWS()
        session = ExotelVoicebotSession(ws, call_id)
        fake_call = _fake_db_call()
        tts_pcm = b"\x03\x00" * (CHUNK_PCM * 8)

        def session_local():
            db = MagicMock()
            db.get.return_value = fake_call
            db.commit = MagicMock()
            db.close = MagicMock()
            db.refresh = MagicMock()
            return db

        stt_calls: list[int] = []

        def fake_transcribe(buf: bytes, *, hint_language: str = "") -> tuple[str, str]:
            stt_calls.append(len(buf))
            return ("పూల్ టైమింగ్స్ ఏమిటి?", "te-IN")

        async def run_session() -> None:
            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
                patch(
                    "app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice",
                    return_value=True,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_tts_pcm_8k",
                    return_value=tts_pcm,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_transcribe_pcm",
                    side_effect=fake_transcribe,
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.process_inbound_speech",
                    return_value=("పూల్ ఉదయం 7 నుండి రాత్రి 9 వరకు.", False),
                ),
                patch.object(ExotelVoicebotSession, "_emit_call_trace", new_callable=AsyncMock),
            ):
                await session.run()

        runner = asyncio.create_task(run_session())
        ws.feed({"event": "connected"})
        ws.feed(
            {
                "event": "start",
                "stream_sid": "st-test",
                "start": {"mediaFormat": {"encoding": "audio/x-mulaw"}},
            }
        )
        await asyncio.sleep(0.08)
        for _ in range(80):
            await asyncio.sleep(0.1)
            pending = [
                s
                for s in ws.sent
                if s.get("event") == "mark"
                and str((s.get("mark") or {}).get("name") or "") not in session._marks_handled
            ]
            for sent in pending:
                ws.feed(
                    {
                        "event": "mark",
                        "stream_sid": "st-test",
                        "mark": sent.get("mark") or {},
                    }
                )
            if MARK_GREETING_PLAYBACK in session._marks_handled:
                break
        pcm = _speech_pcm(1.4)
        for payload in _pcm_to_mulaw_chunks(pcm):
            ws.feed(_media_msg(payload))
            await asyncio.sleep(0.02)
        await asyncio.sleep(3.5)
        ws.feed({"event": "stop"})
        await asyncio.sleep(0.5)
        await asyncio.wait_for(runner, timeout=20.0)
        self.assertGreaterEqual(len(stt_calls), 1, "STT after greeting with real _speak guard")
        outbound = [s for s in ws.sent if s.get("event") == "media"]
        self.assertGreaterEqual(len(outbound), 2, "greeting + answer outbound media")


if __name__ == "__main__":
    unittest.main()