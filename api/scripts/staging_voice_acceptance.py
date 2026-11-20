#!/usr/bin/env python3
"""Staging acceptance: deployment facts, text handler, publish→voice pin, optional WS replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import websockets
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Call, Employee, EmployeeDraft, Workspace
from app.models.enums import EmployeeStatus
from app.services.calls import (
    _employee_snapshot,
    create_browser_voice_preview_call,
    dispatch_inbound_exotel_call,
    resolve_inbound_employee,
)
from app.services.employees import publish_employee, update_draft
from app.services.voice.booking_state import load_booking
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.session_trace import _build_sha
from app.schemas.employee import EmployeeDraftUpdate


def _pg_head() -> str:
    try:
        out = subprocess.run(
            ["alembic", "current"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ},
        )
        for line in out.stdout.splitlines():
            if line and not line.startswith("INFO"):
                return line.strip().split()[0]
    except Exception:
        pass
    return "unknown"


def _health(base: str) -> dict:
    try:
        r = httpx.get(f"{base.rstrip('/')}/health", timeout=5)
        return r.json() if r.status_code == 200 else {"error": r.status_code}
    except Exception as e:
        return {"error": str(e)[:120]}


def text_booking_benchmark() -> dict:
    fields = {
        "employee_brief": "Resort assistant",
        "employee_language": "Telugu",
        "employee_website_knowledge": "Pool opens 8:30 AM. Closes 10 PM.",
        "inbound_chat": {"turns": []},
    }
    call = SimpleNamespace(
        captured_fields=dict(fields),
        transcript="",
        summary="",
        outcome=None,
        finalized_at=None,
        duration_seconds=0,
    )

    class DB:
        def commit(self):
            pass

        def refresh(self, _c):
            pass

    script = [
        "check-in తేదీ 22",
        "25th తేదీ",
        "పూల్ ఎన్ని గంటల వరకు ఓపెన్?",
        "లేదు, చెక్-ఇన్ 21.",
    ]
    replies = []
    with patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True):
        for line in script:
            r, _ = process_inbound_speech(DB(), call, caller_text=line, stt_language="te-IN")
            replies.append(r)
    st = load_booking(call.captured_fields)
    pool_ok = any("8:30" in r or "పూల్" in r for r in replies)
    ok = (
        st.check_in_day == 21
        and st.check_out_day == 25
        and pool_ok
        and not any("మరో విషయం ఏదైనా" in r for r in replies)
    )
    return {
        "pass": ok,
        "check_in_day": st.check_in_day,
        "check_out_day": st.check_out_day,
        "pool_reply_snippet": next((r[:80] for r in replies if "పూల్" in r or "8:30" in r), ""),
    }


def _inbound_test_employee(db) -> Employee | None:
    from app.config import get_settings

    s = get_settings()
    to_raw = (s.exotel_caller_id or "").strip() or "0404590002"
    route = resolve_inbound_employee(db, to_raw=to_raw, settings=s)
    if route:
        emp = db.get(Employee, route[1])
        if emp:
            return emp
    return db.scalars(select(Employee).where(Employee.status == EmployeeStatus.published).limit(1)).first()


def publish_voice_pin_test(db, ws: Workspace, emp: Employee) -> dict:
    """Publish Priya, simulate inbound; draft Shubh without publish; publish Shubh."""
    from app.models.enums import EmployeeStatus

    draft = db.scalars(select(EmployeeDraft).where(EmployeeDraft.employee_id == emp.id)).first()
    if not draft:
        return {"pass": False, "error": "no_draft"}

    update_draft(
        db,
        workspace_id=ws.id,
        employee_id=emp.id,
        body=EmployeeDraftUpdate(tts_speaker="priya", revision=draft.revision),
    )
    db.refresh(draft)
    if emp.status != EmployeeStatus.published:
        publish_employee(db, ws.id, emp.id)
    else:
        update_draft(db, workspace_id=ws.id, employee_id=emp.id, body=EmployeeDraftUpdate(tts_speaker="priya", revision=draft.revision))
        publish_employee(db, ws.id, emp.id)

    snap1 = _employee_snapshot(db, emp)
    call_priya = dispatch_inbound_exotel_call(
        db,
        caller_raw="+919999000001",
        to_raw="test-inbound",
        provider_call_sid=f"pin-priya-{uuid.uuid4().hex[:8]}",
    )
    spk_after_priya_publish = (
        (call_priya.captured_fields or {}).get("tts_speaker") if call_priya else None
    )

    draft = db.scalars(select(EmployeeDraft).where(EmployeeDraft.employee_id == emp.id)).first()
    update_draft(
        db,
        workspace_id=ws.id,
        employee_id=emp.id,
        body=EmployeeDraftUpdate(tts_speaker="shubh", revision=draft.revision),
    )
    call_draft_only = dispatch_inbound_exotel_call(
        db,
        caller_raw="+919999000002",
        to_raw="test-inbound",
        provider_call_sid=f"pin-draft-{uuid.uuid4().hex[:8]}",
    )
    spk_unpublished_draft = (
        (call_draft_only.captured_fields or {}).get("tts_speaker") if call_draft_only else None
    )

    publish_employee(db, ws.id, emp.id)
    snap2 = _employee_snapshot(db, emp)
    call_shubh = dispatch_inbound_exotel_call(
        db,
        caller_raw="+919999000003",
        to_raw="test-inbound",
        provider_call_sid=f"pin-shubh-{uuid.uuid4().hex[:8]}",
    )
    spk_after_shubh_publish = (
        (call_shubh.captured_fields or {}).get("tts_speaker") if call_shubh else None
    )

    ok = (
        snap1.get("tts_speaker") == "priya"
        and spk_after_priya_publish == "priya"
        and spk_unpublished_draft == "priya"
        and snap2.get("tts_speaker") == "shubh"
        and spk_after_shubh_publish == "shubh"
    )
    return {
        "pass": ok,
        "published_priya_snapshot": snap1.get("tts_speaker"),
        "call_while_draft_shubh": spk_unpublished_draft,
        "published_shubh_snapshot": snap2.get("tts_speaker"),
        "preview_override_ignored_on_inbound_pin": spk_after_priya_publish,
    }


async def ws_booking_replay(base_ws: str) -> dict:
    from app.services.voice.sarvam import tts_pcm_8k

    db = SessionLocal()
    ws_row = db.scalars(select(Workspace).limit(1)).first()
    emp = db.scalars(select(Employee).where(Employee.workspace_id == ws_row.id).limit(1)).first()
    snap = _employee_snapshot(db, emp)
    speaker = str(snap.get("tts_speaker") or "shubh")
    call = create_browser_voice_preview_call(
        db, workspace_id=ws_row.id, employee_id=emp.id, tts_speaker=speaker
    )
    call_id = call.id
    fields0 = dict(call.captured_fields or {})
    db.close()

    url = f"{base_ws.rstrip('/')}/v1/ws/exotel/voice/{call_id}"
    sid = "acceptance"
    phrases = [
        ("te-IN", "check in twenty two check in date"),
        ("te-IN", "twenty fifth date checkout"),
        ("te-IN", "pool timings"),
    ]
    transcripts: list[dict] = []
    media_out = 0

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
        await asyncio.sleep(2.8)

        async def reader():
            nonlocal media_out
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
                msg = json.loads(raw)
                if msg.get("event") == "media":
                    media_out += 1
                if msg.get("event") == "transcript":
                    transcripts.append(msg.get("transcript") or {})

        task = asyncio.create_task(reader())
        for lang, text in phrases:
            pcm = tts_pcm_8k(text, lang, speaker=speaker)
            step = 320
            for i in range(0, len(pcm), step):
                chunk = pcm[i : i + step]
                await ws.send(
                    json.dumps(
                        {
                            "event": "media",
                            "stream_sid": sid,
                            "media": {
                                "track": "inbound",
                                "payload": __import__("base64").b64encode(chunk).decode(),
                            },
                        }
                    )
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(2.0)
        await ws.send(json.dumps({"event": "stop"}))
        await asyncio.sleep(0.4)
        task.cancel()

    db = SessionLocal()
    row = db.get(Call, call_id)
    st = load_booking(row.captured_fields if row else {})
    fields = row.captured_fields if row else {}
    db.close()

    agent = [t for t in transcripts if t.get("role") == "agent"]
    caller = [t for t in transcripts if t.get("role") == "caller"]
    heard_pool = any("pool" in (t.get("text") or "").lower() for t in agent)
    ok = media_out >= 8 and len(agent) >= 2 and (st.check_out_day == 25 or st.check_in_day == 22)
    return {
        "pass": ok,
        "call_id": str(call_id),
        "worker_pin_speaker": fields0.get("tts_speaker"),
        "snapshot_revision": fields0.get("employee_snapshot_revision"),
        "media_out": media_out,
        "caller_turns": len(caller),
        "agent_turns": len(agent),
        "heard_pool_answer": heard_pool,
        "booking_in_day": st.check_in_day,
        "booking_out_day": st.check_out_day,
        "transcripts_redacted_roles": [{"role": t.get("role"), "len": len(t.get("text") or "")} for t in transcripts],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8010")
    p.add_argument("--ws-skip", action="store_true", help="Skip Sarvam audio WS replay")
    args = p.parse_args()

    ws_base = args.api.replace("http://", "ws://").replace("https://", "wss://")
    report = {
        "worker_build_sha": _build_sha(),
        "alembic_head": _pg_head(),
        "api_health": _health(args.api),
        "text_booking_benchmark": text_booking_benchmark(),
    }

    db = SessionLocal()
    ws = db.scalars(select(Workspace).limit(1)).first()
    emp = _inbound_test_employee(db) if ws else None
    if ws and emp:
        report["publish_voice_pin"] = publish_voice_pin_test(db, ws, emp)
        report["publish_voice_employee_id"] = str(emp.id)
    else:
        report["publish_voice_pin"] = {"pass": False, "error": "no_workspace_employee"}
    db.close()

    if not args.ws_skip:
        report["real_sarvam_ws_replay"] = asyncio.run(ws_booking_replay(ws_base))

    print(json.dumps(report, indent=2, ensure_ascii=False))

    checks = [
        report["text_booking_benchmark"].get("pass"),
        report.get("publish_voice_pin", {}).get("pass"),
    ]
    if not args.ws_skip:
        checks.append(report.get("real_sarvam_ws_replay", {}).get("pass"))
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())