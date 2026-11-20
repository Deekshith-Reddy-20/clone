#!/usr/bin/env python3
"""Simulated inbound turns (Telugu / Hindi / English) against live Sarvam + conversation logic."""

from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Call
from app.models.enums import CallDirection, CallOutcome
from app.services.voice.inbound_conversation import process_inbound_speech


class _FakeDB:
    def commit(self) -> None:
        pass

    def refresh(self, _c: Call) -> None:
        pass
from app.services.voice.sarvam import (
    _has_devanagari_script,
    _has_telugu_script,
    clamp_voice_lang,
    sanitize_reply_for_lang,
    tts_pcm_8k,
)

SCENARIOS = [
    ("te-IN", "ఈ వీకెండ్ 15 మందికి గదులు ఉన్నాయా?", "te-IN"),
    ("hi-IN", "क्या इस वीकेंड में पंद्रह लोगों के लिए कमरा है?", "hi-IN"),
    ("en-IN", "Any rooms for fifteen guests this weekend?", "en-IN"),
]

FIELDS = {
    "employee_brief": "You are V Farms Resort booking assistant.",
    "employee_language": "Telugu",
    "employee_website_knowledge": "Pool 7 AM to 9 PM. Cottages near Hyderabad.",
    "inbound_chat": {"turns": []},
}


def _call() -> Call:
    c = Call(
        workspace_id=uuid.UUID("b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3"),
        direction=CallDirection.inbound,
        outcome=CallOutcome.connected,
        provider="e2e-test",
        captured_fields=dict(FIELDS),
    )
    return c


def main() -> int:
    db = _FakeDB()
    fails = 0
    for stt_lang, utterance, want in SCENARIOS:
        call = _call()
        t0 = time.time()
        reply, _ = process_inbound_speech(db, call, caller_text=utterance, stt_language=stt_lang)
        lang = clamp_voice_lang((call.captured_fields or {}).get("conversation_language"), want)
        reply = sanitize_reply_for_lang(reply, lang)
        ok_script = (
            (want == "te-IN" and _has_telugu_script(reply))
            or (want == "hi-IN" and _has_devanagari_script(reply))
            or (want == "en-IN" and reply.isascii())
        )
        pcm = tts_pcm_8k(reply, lang)
        ms = int((time.time() - t0) * 1000)
        status = "OK" if ok_script and pcm else "FAIL"
        if status == "FAIL":
            fails += 1
        print(f"{status} {want} lang={lang} tts_bytes={len(pcm)} ms={ms}")
        print(f"  Q: {utterance[:60]}")
        print(f"  A: {reply[:100]}")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())