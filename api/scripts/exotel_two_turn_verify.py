#!/usr/bin/env python3
"""PSTN-style Exotel WS verify: two STT turns before stop (880 ms silence, playback marks)."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import struct
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]

CHUNK_PCM = 3200
MARK_GREETING = "karyuk-greeting-playback-done"
MARK_UTTERANCE = "karyuk-utterance-playback-done"
STREAM_SID = "verify-live"


def _tts_question_pcm(text: str) -> bytes:
    try:
        from app.services.voice.sarvam import tts_pcm_8k

        pcm = tts_pcm_8k(text, "te-IN", rest_only=True)
        if pcm and len(pcm) >= 8000:
            return pcm
    except Exception:
        pass
    return _speech_pcm(1.6)


def _speech_pcm(duration_s: float = 1.6, amp: int = 5000) -> bytes:
    n = int(8000 * duration_s)
    out = bytearray()
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * 220 * i / 8000))
        out += struct.pack("<h", v)
    return bytes(out)


def _lin_payloads(pcm: bytes) -> list[str]:
    out: list[str] = []
    for i in range(0, len(pcm), CHUNK_PCM):
        piece = pcm[i : i + CHUNK_PCM]
        if len(piece) < 2:
            continue
        out.append(base64.b64encode(piece).decode("ascii"))
    return out


async def _send_mark(ws, name: str) -> None:
    await ws.send(
        json.dumps(
            {
                "event": "mark",
                "stream_sid": STREAM_SID,
                "mark": {"name": name},
            }
        )
    )


async def _wait_outbound_burst(
    ws,
    *,
    min_media: int,
    idle_s: float,
    total_timeout_s: float,
) -> tuple[int, str | None]:
    """Accumulate outbound media; return count and last mark name seen from server."""
    media_n = 0
    last_mark: str | None = None
    deadline = time.monotonic() + total_timeout_s
    last_rx = time.monotonic()
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
        except asyncio.TimeoutError:
            if media_n >= min_media and (time.monotonic() - last_rx) >= idle_s:
                return media_n, last_mark
            continue
        last_rx = time.monotonic()
        msg = json.loads(raw)
        ev = msg.get("event")
        if ev == "media":
            media_n += 1
        elif ev == "mark":
            last_mark = str((msg.get("mark") or {}).get("name") or "") or None

    return media_n, last_mark


async def _playout_ack(ws, mark_from_server: str | None, play_s_estimate: float) -> None:
    """Simulate Exotel: after agent audio, return playback-complete mark."""
    if mark_from_server:
        await asyncio.sleep(min(max(play_s_estimate, 0.3), 8.0))
        await _send_mark(ws, mark_from_server)
    elif mark_from_server is None and play_s_estimate > 0:
        await asyncio.sleep(min(play_s_estimate, 8.0))
        await _send_mark(ws, MARK_GREETING)


async def _send_utterance(ws, pcm: bytes) -> None:
    for payload in _lin_payloads(pcm):
        await ws.send(
            json.dumps(
                {
                    "event": "media",
                    "stream_sid": STREAM_SID,
                    "media": {"track": "inbound", "payload": payload},
                }
            )
        )
        await asyncio.sleep(0.02)


async def _run(url: str, log_path: str | None, *, call_id_prefix: str) -> dict:
    if websockets is None:
        return {"ok": False, "error": "websockets missing"}

    stages: list[str] = []

    async with websockets.connect(url, open_timeout=10) as ws:
        await ws.send(json.dumps({"event": "connected"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "stream_sid": STREAM_SID,
                    "start": {"mediaFormat": {"encoding": "base64", "sampleRate": 8000}},
                }
            )
        )
        await asyncio.sleep(0.15)

        greet_n, greet_mark = await _wait_outbound_burst(
            ws, min_media=8, idle_s=0.35, total_timeout_s=45.0
        )
        await _playout_ack(ws, greet_mark or MARK_GREETING, play_s_estimate=greet_n * 0.1 + 0.5)
        await asyncio.sleep(1.1)

        await _send_utterance(ws, _tts_question_pcm("హాస్పిటల్ ఎక్కడ ఉంది?"))
        await asyncio.sleep(1.0)
        q1_n, reply_mark = await _wait_outbound_burst(
            ws, min_media=3, idle_s=0.4, total_timeout_s=55.0
        )
        await _playout_ack(ws, reply_mark or MARK_UTTERANCE, play_s_estimate=q1_n * 0.1 + 0.4)
        await asyncio.sleep(1.2)

        await _send_utterance(ws, _tts_question_pcm("OPD టైమింగ్స్ ఎంటి?"))
        await asyncio.sleep(1.0)
        q2_n, reply2_mark = await _wait_outbound_burst(
            ws, min_media=3, idle_s=0.4, total_timeout_s=55.0
        )
        await _playout_ack(ws, reply2_mark or MARK_UTTERANCE, play_s_estimate=q2_n * 0.1 + 0.4)
        await asyncio.sleep(0.5)
        await ws.send(json.dumps({"event": "stop"}))
        await asyncio.sleep(1.0)

    if log_path and os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "voice_pipeline" not in line:
                    continue
                if call_id_prefix and call_id_prefix not in line:
                    continue
                for stage in (
                    "playback_mark",
                    "listen_gate_open",
                    "stt_request",
                    "stt_final",
                    "stt_provider_error",
                    "exotel_stop",
                ):
                    if f'"stage": "{stage}"' in line:
                        stages.append(stage)

    stt_req = stages.count("stt_request")
    stt_fin = stages.count("stt_final")
    mid_call_stt = False
    if stt_req >= 1 and "exotel_stop" in stages and "stt_request" in stages:
        mid_call_stt = stages.index("stt_request") < stages.index("exotel_stop")
    ok = (
        greet_n >= 8
        and q1_n >= 3
        and q2_n >= 3
        and stt_req >= 2
        and stt_fin >= 2
        and mid_call_stt
    )
    return {
        "ok": ok,
        "greeting_outbound_media": greet_n,
        "q1_reply_outbound_media": q1_n,
        "q2_reply_outbound_media": q2_n,
        "pipeline_stages": stages,
        "stt_request_count": stt_req,
        "stt_final_count": stt_fin,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--call-id", type=uuid.UUID, required=True)
    parser.add_argument("--base-url", default="ws://127.0.0.1:8010")
    parser.add_argument(
        "--log-file",
        default="/tmp/karyuk-cc-8010.log",
        help="Worker log for voice_pipeline stage counting",
    )
    args = parser.parse_args()
    prefix = str(args.call_id)[:8]
    url = f"{args.base_url.rstrip('/')}/v1/ws/exotel/voice/{args.call_id}"
    result = asyncio.run(_run(url, args.log_file, call_id_prefix=prefix))
    result["call_id_prefix"] = prefix
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())