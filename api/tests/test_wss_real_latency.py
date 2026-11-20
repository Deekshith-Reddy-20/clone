"""Real WSS latency harness: replay 8 kHz PCM WAVs through ExotelVoicebotSession."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import statistics
import struct
import unittest
import uuid
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models import Call
from app.services.voice.exotel_voicebot_session import ExotelVoicebotSession

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
WAV_NAMES = [
    "01_location.wav",
    "02_price.wav",
    "03_booking_dates.wav",
    "04_manager.wav",
    "05_compliment.wav",
    "06_noisy_background.wav",
    "07_long_pause.wav",
    "08_interruption.wav",
    "09_codemix_location.wav",
    "10_short_ack.wav",
]


def _load_pcm(wav_path: Path) -> bytes:
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getframerate() == 8000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        return wf.readframes(wf.getnframes())


def _chunks_b64(pcm: bytes, frame_bytes: int = 3200) -> list[str]:
    out: list[str] = []
    for i in range(0, len(pcm), frame_bytes):
        piece = pcm[i : i + frame_bytes]
        if piece:
            out.append(base64.b64encode(piece).decode("ascii"))
    return out


class MockExotelWS:
    def __init__(self) -> None:
        self._in: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []
        self.first_media_at: float | None = None
        self.marks: list[str] = []

    def feed(self, msg: dict) -> None:
        self._in.put_nowait(json.dumps(msg))

    async def receive_text(self) -> str:
        return await self._in.get()

    async def send_json(self, data: dict) -> None:
        if data.get("event") == "media" and self.first_media_at is None:
            self.first_media_at = asyncio.get_event_loop().time()
        if data.get("event") == "mark":
            self.marks.append(str((data.get("mark") or {}).get("name") or ""))
        self.sent.append(data)


def _fake_call() -> Call:
    call = MagicMock(spec=Call)
    call.captured_fields = {
        "employee_brief": "V Farms resort assistant.",
        "employee_language": "Telugu",
        "employee_website_knowledge": "Pool 7 AM to 9 PM.",
        "inbound_chat": {"turns": []},
        "conversation_language": "te-IN",
    }
    return call


class WssRealLatencyHarness(unittest.IsolatedAsyncioTestCase):
    async def test_replay_wavs_report_metrics(self) -> None:
        if not AUDIO_DIR.is_dir():
            self.skipTest("tests/audio missing — record 10 Telugu/codemix WAVs on a phone")
        missing = [n for n in WAV_NAMES if not (AUDIO_DIR / n).is_file()]
        if missing:
            self.skipTest(f"missing WAVs: {missing}")

        os.environ["KARYUK_PSTN_STREAM"] = "0"
        os.environ["VOICE_BARGE_IN"] = "on"
        results: list[dict] = []

        for name in WAV_NAMES:
            pcm = _load_pcm(AUDIO_DIR / name)
            call_id = uuid.uuid4()
            ws = MockExotelWS()
            session = ExotelVoicebotSession(ws, call_id)
            session.stream_sid = "st-harness"
            eos_at = asyncio.get_event_loop().time()

            async def _run() -> None:
                ws.feed({"event": "connected"})
                ws.feed(
                    {
                        "event": "start",
                        "stream_sid": "st-harness",
                        "start": {"mediaFormat": {"encoding": "linear16", "sampleRate": 8000}},
                    }
                )
                for payload in _chunks_b64(pcm):
                    ws.feed(
                        {
                            "event": "media",
                            "stream_sid": "st-harness",
                            "media": {"track": "inbound", "payload": payload},
                        }
                    )
                ws.feed({"event": "stop", "stream_sid": "st-harness"})

            with (
                patch("app.services.voice.exotel_voicebot_session.SessionLocal") as mock_db,
                patch(
                    "app.services.voice.inbound_pstn_stream.iter_inbound_llm_stream",
                    return_value=_async_empty(),
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.process_inbound_speech",
                    return_value=("సరే అండి, చెప్పండి.", False),
                ),
                patch(
                    "app.services.voice.exotel_voicebot_session.sarvam_tts_pcm_8k",
                    return_value=b"\x00\x01" * 4000,
                ),
            ):
                mock_db.return_value.__enter__ = lambda s: s
                mock_db.return_value.__exit__ = lambda *a: None
                mock_db.return_value.get.return_value = _fake_call()
                task = asyncio.create_task(session.run())
                await _run()
                try:
                    await asyncio.wait_for(task, timeout=25.0)
                except asyncio.TimeoutError:
                    task.cancel()

            e2e = int((ws.first_media_at - eos_at) * 1000) if ws.first_media_at else None
            results.append(
                {
                    "file": name,
                    "e2e_ms": e2e,
                    "barge_marks": len([m for m in ws.marks if m.startswith("karyuk")]),
                    "out_media": sum(1 for s in ws.sent if s.get("event") == "media"),
                }
            )

        e2e_vals = [r["e2e_ms"] for r in results if r["e2e_ms"] is not None]
        if e2e_vals:
            p50 = statistics.median(e2e_vals)
            p95 = sorted(e2e_vals)[max(0, int(0.95 * (len(e2e_vals) - 1)))]
            print(f"REAL_HARNESS e2e_ms p50={p50:.0f} p95={p95:.0f} n={len(e2e_vals)}")
        for row in results:
            print("REAL_HARNESS", row)
        self.assertTrue(any(r["out_media"] > 0 for r in results))


async def _async_empty():
    if False:
        yield ("tools", [])