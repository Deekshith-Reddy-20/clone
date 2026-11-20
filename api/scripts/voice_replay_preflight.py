#!/usr/bin/env python3
"""Preflight + Sarvam STT on booking fixture phrases (before WS replay)."""

from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_settings
from app.database import SessionLocal
from app.models import Employee
from app.services.calls import (
    _employee_snapshot,
    create_inbound_voice_replay_call,
    resolve_inbound_employee,
)
from app.services.employees import get_draft
from app.services.voice.booking_state import load_booking
from app.services.voice.sarvam import transcribe_pcm, tts_pcm_8k
from app.services.voice.session_trace import _build_sha

FIXTURES = [
    "ఇరవై రెండో తేదీ చెక్ ఇన్",
    "ఇరవై ఐదో తేదీ",
    "పూల్ ఎన్ని గంటల వరకు ఓపెన్",
    "లేదు, చెక్-ఇన్ ఇరవై ఒకటి",
]


def main() -> int:
    db = SessionLocal()
    s = get_settings()
    to_raw = (s.exotel_caller_id or "").strip() or "0404590002"
    route = resolve_inbound_employee(db, to_raw=to_raw, settings=s)
    if not route:
        print(json.dumps({"error": "no_inbound_route"}))
        return 1
    emp = db.get(Employee, route[1])
    snap = _employee_snapshot(db, emp)
    draft = get_draft(db, emp.id)
    emp_id = str(emp.id)
    draft_revision = draft.revision if draft else None
    call = create_inbound_voice_replay_call(
        db,
        caller_raw="+919999000099",
        to_raw=to_raw,
        provider_call_sid=f"preflight-{uuid.uuid4().hex[:10]}",
    )
    pin = dict((call.captured_fields if call else {}) or {})
    stt_rows = []
    speaker = str(snap.get("tts_speaker") or pin.get("tts_speaker") or "shubh")
    for phrase in FIXTURES:
        pcm = tts_pcm_8k(phrase, "te-IN", speaker=speaker)
        text, lang = transcribe_pcm(pcm, hint_language="te-IN")
        stt_rows.append(
            {
                "fixture": phrase,
                "stt_text": text,
                "stt_lang": lang,
                "pcm_bytes": len(pcm),
            }
        )
    db.close()
    out = {
        "worker_build_sha": _build_sha(),
        "employee_id": emp_id,
        "published_snapshot_revision": snap.get("revision"),
        "published_version_number": snap.get("version_number"),
        "draft_revision": draft_revision,
        "pinned_call_revision": pin.get("employee_snapshot_revision"),
        "pinned_version_number": pin.get("employee_version_number"),
        "pinned_speaker": pin.get("tts_speaker"),
        "knowledge_state": pin.get("knowledge_state"),
        "knowledge_len": len(str(pin.get("employee_website_knowledge") or "")),
        "draft_vs_published_note": (
            "UI draft revision can exceed published snapshot revision until you publish again."
        ),
        "stt_fixtures": stt_rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())