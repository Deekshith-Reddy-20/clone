#!/usr/bin/env python3
"""
Replay Exotel Voicebot WebSocket with timed inbound µ-law media (no text injection).

Usage:
  python scripts/exotel_ws_replay_test.py --mode mock --langs te,hi,en
  python scripts/exotel_ws_replay_test.py --mode sarvam --langs te --base-url ws://127.0.0.1:8010

Requires a Call row: pass --call-id UUID or set EXOTEL_REPLAY_CALL_ID.
"""

from __future__ import annotations

import argparse
import asyncio
import audioop
import base64
import json
import math
import os
import struct
import sys
import time
import uuid
import wave
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore

LANG_UTTERANCES = {
    "te": [
        "ఈ వీకెండ్ పదಹేదు మందికి గదులు ఉన్నాయా?",
        "పూల్ టైమింగ్స్ ఏమిటి?",
    ],
    "hi": [
        "क्या इस वीकेंड पंद्रह लोगों के लिए कमरा है?",
        "पूल कितने बजे खुलता है?",
    ],
    "en": [
        "Any rooms for fifteen guests this weekend?",
        "What are the pool timings?",
    ],
}


def _synthetic_pcm(duration_s: float, amp: int = 4500) -> bytes:
    n = int(8000 * duration_s)
    out = bytearray()
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * 280 * i / 8000))
        out += struct.pack("<h", v)
    return bytes(out)


def _utterance_pcm(mode: str, lang: str, index: int) -> bytes:
    text = LANG_UTTERANCES[lang][index]
    if mode == "sarvam":
        from app.services.voice.sarvam import tts_pcm_8k

        bcp47 = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}[lang]
        pcm = tts_pcm_8k(text, bcp47)
        if len(pcm) >= 4000:
            return pcm
    return _synthetic_pcm(1.6)


def _mulaw_payloads(pcm: bytes, frame_ms: int = 20) -> list[str]:
    step = int(8000 * frame_ms / 1000) * 2
    out: list[str] = []
    for i in range(0, len(pcm), step):
        piece = pcm[i : i + step]
        if len(piece) < 2:
            continue
        out.append(base64.b64encode(audioop.lin2ulaw(piece, 2)).decode("ascii"))
    return out


def _decode_outbound_pcm(sent_events: list[dict]) -> bytes:
    chunks: list[bytes] = []
    for ev in sent_events:
        if ev.get("event") != "media":
            continue
        payload = (ev.get("media") or {}).get("payload") or ""
        if not payload:
            continue
        raw = base64.b64decode(payload)
        if len(raw) % 2 == 0:
            chunks.append(raw)
    return b"".join(chunks)


async def _mock_replay_lang(lang: str) -> dict:
    """In-process mock WS (same as unit test) — no live server."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.models import Call
    from app.services.voice.exotel_voicebot_session import CHUNK_PCM, ExotelVoicebotSession
    from tests.test_exotel_voicebot_ws import MockExotelWS, _media_msg

    call_id = uuid.uuid4()
    ws = MockExotelWS()
    session = ExotelVoicebotSession(ws, call_id)
    fake_call = MagicMock(spec=Call)
    fake_call.captured_fields = {
        "employee_brief": "V Farms.",
        "employee_language": {"te": "Telugu", "hi": "Hindi", "en": "English"}[lang],
        "employee_website_knowledge": "Pool open 7 AM to 9 PM.",
        "inbound_chat": {"turns": []},
    }
    bcp47 = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}[lang]

    def session_local():
        db = MagicMock()
        db.get.return_value = fake_call
        db.commit = MagicMock()
        db.close = MagicMock()
        db.refresh = MagicMock()
        return db

    tts_pcm = b"\x02\x00" * (CHUNK_PCM * 6)
    stt_idx = 0

    def fake_stt(buf: bytes, *, hint_language: str = "") -> tuple[str, str]:
        nonlocal stt_idx
        text = LANG_UTTERANCES[lang][min(stt_idx, 1)]
        stt_idx += 1
        return text, bcp47

    async def fast_speak(self, text: str) -> None:
        self.speaking = True
        await self._send_wire_audio(tts_pcm[:CHUNK_PCM * 2])
        self.speaking = False
        self._playback_until = time.monotonic() + 0.35
        self._ignore_input_until = self._playback_until

    async def run_session() -> None:
        with (
            patch("app.services.voice.exotel_voicebot_session.SessionLocal", session_local),
            patch("app.services.voice.exotel_voicebot_session.use_sarvam_inbound_voice", return_value=True),
            patch("app.services.voice.exotel_voicebot_session.sarvam_tts_pcm_8k", return_value=tts_pcm),
            patch("app.services.voice.exotel_voicebot_session.sarvam_transcribe_pcm", side_effect=fake_stt),
            patch(
                "app.services.voice.exotel_voicebot_session.process_inbound_speech",
                side_effect=[
                    (f"Answer one ({lang})", False),
                    (f"Answer two ({lang})", False),
                ],
            ),
            patch.object(ExotelVoicebotSession, "_speak", fast_speak),
            patch.object(ExotelVoicebotSession, "_emit_call_trace", new_callable=AsyncMock),
        ):
            await session.run()

    t0 = time.monotonic()
    runner = asyncio.create_task(run_session())
    ws.feed({"event": "connected"})
    ws.feed(
        {
            "event": "start",
            "stream_sid": "mock",
            "start": {"mediaFormat": {"encoding": "audio/x-mulaw"}},
        }
    )
    await asyncio.sleep(0.04)

    for q in range(2):
        pcm = _utterance_pcm("mock", lang, q)
        # First question starts as greeting playback tail is active.
        for payload in _mulaw_payloads(pcm):
            ws.feed(_media_msg(payload, "mock"))
            await asyncio.sleep(0.02)
        await asyncio.sleep(2.0)

    ws.feed({"event": "stop"})
    await asyncio.wait_for(runner, timeout=12.0)
    pcm_out = _decode_outbound_pcm(ws.sent)
    return {
        "lang": lang,
        "mode": "mock",
        "stt_turns": stt_idx,
        "outbound_media": sum(1 for s in ws.sent if s.get("event") == "media"),
        "outbound_pcm_bytes": len(pcm_out),
        "elapsed_s": round(time.monotonic() - t0, 2),
        "ok": stt_idx >= 2 and len(pcm_out) > 8000,
    }


async def _live_ws_replay(
    *,
    base_url: str,
    call_id: uuid.UUID,
    mode: str,
    lang: str,
    out_dir: Path,
) -> dict:
    if websockets is None:
        return {"lang": lang, "mode": mode, "ok": False, "error": "websockets package missing"}

    url = f"{base_url.rstrip('/')}/v1/ws/exotel/voice/{call_id}"
    sent_collect: list[dict] = []
    stt_guess = 0
    t0 = time.monotonic()

    async with websockets.connect(url) as ws_conn:
        await ws_conn.send(json.dumps({"event": "connected"}))
        await ws_conn.send(
            json.dumps(
                {
                    "event": "start",
                    "stream_sid": "replay",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw"}},
                }
            )
        )
        await asyncio.sleep(0.5)

        for q in range(2):
            pcm = _utterance_pcm(mode, lang, q)
            for payload in _mulaw_payloads(pcm):
                await ws_conn.send(
                    json.dumps(
                        {
                            "event": "media",
                            "stream_sid": "replay",
                            "media": {"track": "inbound", "payload": payload},
                        }
                    )
                )
                await asyncio.sleep(0.02)
            stt_guess += 1
            await asyncio.sleep(2.2)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws_conn.recv(), timeout=0.3)
                sent_collect.append(json.loads(raw))
            except asyncio.TimeoutError:
                continue
        await ws_conn.send(json.dumps({"event": "stop"}))

    pcm_out = _decode_outbound_pcm(sent_collect)
    wav_path = out_dir / f"replay_{mode}_{lang}_{call_id.hex[:8]}.wav"
    if pcm_out:
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(pcm_out)

    return {
        "lang": lang,
        "mode": mode,
        "call_id": str(call_id),
        "outbound_media": len([e for e in sent_collect if e.get("event") == "media"]),
        "outbound_pcm_bytes": len(pcm_out),
        "wav": str(wav_path) if pcm_out else "",
        "elapsed_s": round(time.monotonic() - t0, 2),
        "ok": len(pcm_out) > 16_000,
    }


async def main_async(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fails = 0
    results: list[dict] = []

    for lang in args.langs:
        if args.mode == "mock":
            r = await _mock_replay_lang(lang)
            results.append(r)
            if not r.get("ok"):
                fails += 1
            print(json.dumps(r, ensure_ascii=False))
            continue

        call_s = args.call_id or os.environ.get("EXOTEL_REPLAY_CALL_ID", "")
        if not call_s:
            print("FAIL: --call-id or EXOTEL_REPLAY_CALL_ID required for sarvam/live ws replay")
            return 2
        r = await _live_ws_replay(
            base_url=args.base_url,
            call_id=uuid.UUID(call_s),
            mode=args.mode,
            lang=lang,
            out_dir=out_dir,
        )
        results.append(r)
        if not r.get("ok"):
            fails += 1
        print(json.dumps(r, ensure_ascii=False))

    summary_path = out_dir / "replay_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"summary -> {summary_path}")
    return fails


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("mock", "sarvam"), default="mock")
    p.add_argument("--langs", default="te,hi,en")
    p.add_argument("--base-url", default=os.environ.get("EXOTEL_REPLAY_WS", "ws://127.0.0.1:8010"))
    p.add_argument("--call-id", default="")
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "tmp", "exotel_replay"))
    args = p.parse_args()
    args.langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())