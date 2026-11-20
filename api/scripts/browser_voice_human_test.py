#!/usr/bin/env python3
"""WS replay — dispatch pin; waits each turn (STT + reply + audio) before stop."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import websockets
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Call, Employee, Workspace
from app.services.calls import (
    SYNTHETIC_REPLAY_KNOWLEDGE,
    _employee_snapshot,
    create_inbound_voice_replay_call,
    resolve_inbound_employee,
)
from app.services.employees import get_draft
from app.services.voice.booking_state import load_booking
from app.services.voice.sarvam import tts_pcm_8k
from app.services.voice.session_trace import _build_sha

DEFAULT_QUESTIONS = [
    ("te-IN", "ఈ వీకెండ్ పదహేదు మందికి గదులు ఉన్నాయా?"),
    ("te-IN", "పూల్ ఏ సమయానికి ఓపెన్ అవుతుంది?"),
]

BOOKING_BENCHMARK = [
    ("te-IN", "చెక్-ఇన్ ఇరవై రెండో తేదీ"),
    ("te-IN", "ఇరవై ఐదో తేదీ"),
    ("te-IN", "పూల్ ఎన్ని గంటలకు తెరుస్తారు?"),
    ("te-IN", "లేదు, చెక్-ఇన్ ఇరవై ఒకటో తేదీ"),
]

TURN_WAIT_S = 42.0
POST_MARK_S = 0.38


def _pool_time_in_knowledge(knowledge: str) -> str | None:
    import re

    m = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM)?|\d{1,2}\s*(?:AM|PM))", knowledge or "", re.I)
    return m.group(1).replace(" ", "") if m else None


async def send_utterance(ws, pcm: bytes, stream_sid: str) -> None:
    pcm = pcm + (b"\x00\x00" * 6400)
    step = 320
    for i in range(0, len(pcm), step):
        chunk = pcm[i : i + step]
        await ws.send(
            json.dumps(
                {
                    "event": "media",
                    "stream_sid": stream_sid,
                    "media": {"track": "inbound", "payload": base64.b64encode(chunk).decode()},
                }
            )
        )
        await asyncio.sleep(0.02)


def _preflight_config(db, emp: Employee, pin: dict) -> dict:
    snap = _employee_snapshot(db, emp)
    draft = get_draft(db, emp.id)
    return {
        "worker_build_sha": _build_sha(),
        "employee_id": str(emp.id),
        "published_snapshot_revision": str(snap.get("revision") or ""),
        "published_version_number": str(snap.get("version_number") or ""),
        "published_call_mode": str(snap.get("mode") or ""),
        "draft_revision": draft.revision if draft else None,
        "draft_call_mode": draft.mode.value if draft and hasattr(draft.mode, "value") else str(draft.mode) if draft else None,
        "pinned_snapshot_revision": str(pin.get("employee_snapshot_revision") or ""),
        "pinned_version_number": str(pin.get("employee_version_number") or ""),
        "pinned_call_mode": str(pin.get("employee_mode") or ""),
        "knowledge_state": pin.get("knowledge_state"),
        "pinned_speaker": pin.get("tts_speaker"),
        "published_knowledge_chars": len(str(snap.get("website_knowledge") or "").strip()),
        "pinned_knowledge_chars": len(str(pin.get("employee_website_knowledge") or "").strip()),
        "knowledge_pool_hint": _pool_time_in_knowledge(
            str(pin.get("employee_website_knowledge") or "")
        ),
        "dispatch_uses_published_snapshot": True,
        "config_match": (
            str(snap.get("revision") or "") == str(pin.get("employee_snapshot_revision") or "")
            and str(snap.get("version_number") or "") == str(pin.get("employee_version_number") or "")
        ),
    }


async def wait_for_greeting(mark_times: list[float], *, timeout: float = 22.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mark_times:
            return True
        await asyncio.sleep(0.2)
    return False


async def wait_for_turn(
    turn_id: int,
    transcripts: list[dict],
    media_out: list[int],
    media_before: int,
    mark_times: list[float],
    marks_before: int,
    *,
    timeout: float = TURN_WAIT_S,
) -> dict:
    """Caller+agent transcript with turn_id, outbound audio, and utterance mark."""
    deadline = time.time() + timeout
    last: dict = {"ok": False, "turn_id": turn_id}
    while time.time() < deadline:
        caller = next(
            (t for t in transcripts if t.get("role") == "caller" and t.get("turn_id") == turn_id),
            None,
        )
        agent = next(
            (t for t in transcripts if t.get("role") == "agent" and t.get("turn_id") == turn_id),
            None,
        )
        audio_ok = media_out[0] > media_before
        mark_ok = len(mark_times) > marks_before
        if caller and agent and audio_ok and mark_ok:
            last = {
                "ok": True,
                "turn_id": turn_id,
                "stt_caller": caller.get("text"),
                "agent_reply": agent.get("text"),
                "media_out_delta": media_out[0] - media_before,
            }
            return last
        await asyncio.sleep(0.22)
    last.update(
        {
            "stt_caller": next(
                (
                    t.get("text")
                    for t in transcripts
                    if t.get("role") == "caller" and t.get("turn_id") == turn_id
                ),
                None,
            ),
            "agent_reply": next(
                (
                    t.get("text")
                    for t in transcripts
                    if t.get("role") == "agent" and t.get("turn_id") == turn_id
                ),
                None,
            ),
            "media_out_delta": media_out[0] - media_before,
            "marks_seen": len(mark_times) - marks_before,
        }
    )
    return last


async def run() -> int:
    use_booking = "--booking" in sys.argv
    live_pin = "--live" in sys.argv
    questions = BOOKING_BENCHMARK if use_booking else DEFAULT_QUESTIONS
    db = SessionLocal()
    ws_row = db.scalars(select(Workspace).limit(1)).first()
    s = get_settings()
    to_raw = (s.exotel_caller_id or "").strip() or "0404590002"
    route = resolve_inbound_employee(db, to_raw=to_raw, settings=s)
    emp = db.get(Employee, route[1]) if route else None
    if not emp:
        emp = db.scalars(select(Employee).where(Employee.workspace_id == ws_row.id).limit(1)).first()
    snap = _employee_snapshot(db, emp)
    speaker = str(snap.get("tts_speaker") or "shubh")
    call = create_inbound_voice_replay_call(
        db,
        caller_raw="+919999000088",
        to_raw=to_raw,
        provider_call_sid=f"replay-{uuid.uuid4().hex[:12]}",
        synthetic_knowledge=None if live_pin else SYNTHETIC_REPLAY_KNOWLEDGE,
    )
    if not call:
        db.close()
        print(json.dumps({"error": "dispatch_failed", "employee_id": str(emp.id)}))
        return 1
    call_id = call.id
    pin_fields = dict(call.captured_fields or {})
    preflight = _preflight_config(db, emp, pin_fields)
    db.close()

    url = f"ws://127.0.0.1:8010/v1/ws/exotel/voice/{call_id}"
    sid = "human-test"
    transcripts: list[dict] = []
    media_out = [0]
    mark_times: list[float] = []
    turn_trace: list[dict] = []
    t0 = time.time()
    first_fail_turn: dict | None = None

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"event": "connected"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "stream_sid": sid,
                    "start": {"mediaFormat": {"encoding": "audio/l16", "sampleRate": 8000}},
                }
            )
        )

        async def reader():
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
                msg = json.loads(raw)
                if msg.get("event") == "media":
                    media_out[0] += 1
                if msg.get("event") == "transcript":
                    tr = msg.get("transcript") or {}
                    transcripts.append(tr)
                if msg.get("event") == "mark":
                    mark_times.append(time.time())

        task = asyncio.create_task(reader())
        await wait_for_greeting(mark_times)
        await asyncio.sleep(POST_MARK_S)

        for idx, (lang, text) in enumerate(questions, start=1):
            turn_id = idx
            marks_before = len(mark_times)
            media_before = media_out[0]
            turn_trace.append({"turn_id": turn_id, "fixture": text})
            pcm = tts_pcm_8k(text, lang, speaker=speaker)
            if len(pcm) < 4000:
                print("FAIL tts", text[:40])
                return 1
            await send_utterance(ws, pcm, sid)
            result = await wait_for_turn(
                turn_id,
                transcripts,
                media_out,
                media_before,
                mark_times,
                marks_before,
                timeout=TURN_WAIT_S,
            )
            turn_trace[-1].update(result)
            if not result.get("ok") and first_fail_turn is None:
                first_fail_turn = {"stage": "spoken_turn", "turn_id": turn_id, **result}

        await ws.send(json.dumps({"event": "stop"}))
        await asyncio.sleep(0.35)
        task.cancel()

    db2 = SessionLocal()
    row = db2.get(Call, call_id)
    st = load_booking(row.captured_fields if row else {})
    db2.close()

    pool_hint = preflight.get("knowledge_pool_hint") or ""
    if live_pin:
        pool_heard = any(
            "పూల్" in (t.get("text") or "")
            and (
                (pool_hint and pool_hint[:4] in (t.get("text") or ""))
                or "నాలెడ్జ్" in (t.get("text") or "")
                or "published" in (t.get("text") or "").lower()
            )
            for t in transcripts
            if t.get("role") == "agent"
        )
    else:
        pool_heard = any(
            (pool_hint and pool_hint[:4] in (t.get("text") or ""))
            or "పూల్" in (t.get("text") or "")
            for t in transcripts
            if t.get("role") == "agent"
        )

    turns_ok = all(t.get("ok") for t in turn_trace) if turn_trace else False
    state_ok = st.check_in_day == 21 and st.check_out_day == 25 if use_booking else True
    correction_heard = any(
        t.get("role") == "agent" and t.get("turn_id") == 4 and ("21" in (t.get("text") or "") or "మార్చ" in (t.get("text") or ""))
        for t in transcripts
    )
    ok = (
        preflight.get("config_match")
        and turns_ok
        and state_ok
        and pool_heard
        and (correction_heard or not use_booking)
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "mode": "live" if live_pin else "fixture",
                "preflight": preflight,
                "call_id": str(call_id),
                "media_out": media_out[0],
                "booking_in_day": st.check_in_day,
                "booking_out_day": st.check_out_day,
                "pool_answer_heard": pool_heard,
                "correction_reply_heard": correction_heard,
                "first_fail_turn": first_fail_turn,
                "turn_trace": turn_trace,
                "transcripts": transcripts,
                "elapsed_s": round(time.time() - t0, 1),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))