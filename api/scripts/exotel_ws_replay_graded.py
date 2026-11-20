#!/usr/bin/env python3
"""
Graded Exotel WS replay with real Sarvam audio (µ-law in), DB turn check, optional answer STT.

Extends exotel_ws_replay_test — use that script's --mode sarvam --base-url --call-id.

This runner creates Call rows, runs pool-faq / default scenarios, grades replies against uploaded docs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from uuid import UUID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Call, Employee, Workspace
from app.services.calls import create_browser_voice_preview_call

import importlib.util

_rp = Path(__file__).with_name("exotel_ws_replay_test.py")
_spec = importlib.util.spec_from_file_location("exotel_ws_replay_test", _rp)
_replay = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(_replay)
LANG_UTTERANCES = _replay.LANG_UTTERANCES
_decode_outbound_pcm = _replay._decode_outbound_pcm
_mulaw_payloads = _replay._mulaw_payloads

try:
    import websockets
except ImportError:
    websockets = None

KNOWLEDGE_REV = {
    "v1": "Swimming pool opens daily at 8:30 AM. Closes at 10 PM. No spa details listed.",
    "v2": "Swimming pool opens daily at 6:00 AM. Closes at 9 PM. No spa details listed.",
}

POOL_QUESTIONS = {
    "te": [
        "పూల్ పొద్దున ఎన్ని గంటలకు తెరుస్తారు?",
        "అది హీటెడ్ పూలా?",
    ],
    "hi": [
        "पूल सुबह कितने बजे खुलता है?",
        "क्या यह हीटेड पूल है?",
    ],
    "en": [
        "What time does the pool open in the morning?",
        "Is it a heated pool?",
    ],
}

LANG_ECHO_SEQUENCE = [
    ("हाँ जी हाँ जी", "reject_echo"),
    ("फीस कितनी है?", "answer_fee"),
    ("తెలుగులో మాట్లాడండి", "switch_te"),
    ("అవును", "ack_te"),
]


def _questions_for(lang: str, scenario: str) -> list[str]:
    if scenario == "pool-faq":
        return list(POOL_QUESTIONS[lang])
    return list(LANG_UTTERANCES[lang][:2])


def _tts_utterance_pcm(text: str, bcp47: str) -> bytes:
    from app.services.voice.sarvam import tts_pcm_8k

    pcm = tts_pcm_8k(text, bcp47)
    return pcm if len(pcm) >= 4000 else pcm


def _create_call(*, knowledge: str, employee_lang: str, revision: str) -> UUID:
    db = SessionLocal()
    try:
        ws = db.scalars(select(Workspace).limit(1)).first()
        emp = db.scalars(select(Employee).where(Employee.workspace_id == ws.id).limit(1)).first()
        call = create_browser_voice_preview_call(
            db, workspace_id=ws.id, employee_id=emp.id, tts_speaker="priya"
        )
        fields = dict(call.captured_fields or {})
        fields.update(
            {
                "employee_language": employee_lang,
                "employee_website_knowledge": knowledge,
                "employee_snapshot_revision": revision,
                "knowledge_state": "published",
                "conversation_language": {"Telugu": "te-IN", "Hindi": "hi-IN", "English": "en-IN"}[
                    employee_lang
                ],
            }
        )
        call.captured_fields = fields
        db.commit()
        return call.id
    finally:
        db.close()


def _load_call_grades(call_id: UUID) -> dict:
    db = SessionLocal()
    try:
        call = db.get(Call, call_id)
        if not call:
            return {"error": "call_not_found"}
        fields = call.captured_fields or {}
        turns = (fields.get("inbound_chat") or {}).get("turns") or []
        users = [t.get("text", "") for t in turns if t.get("role") == "user"]
        agents = [t.get("text", "") for t in turns if t.get("role") == "assistant"]
        return {
            "conv_lang": fields.get("conversation_language"),
            "user_turns": users,
            "agent_turns": agents,
            "n_user": len(users),
            "n_agent": len(agents),
        }
    finally:
        db.close()


def _transcribe_answer_snippets(pcm: bytes, *, skip_leading_samples: int = 90000) -> list[str]:
    """Sarvam STT on post-greeting outbound slices (~11s skip default greeting)."""
    from app.services.voice.sarvam import transcribe_pcm

    if len(pcm) < skip_leading_samples + 8000:
        return []
    rest = pcm[skip_leading_samples:]
    chunk = 24000  # ~3s
    out: list[str] = []
    for i in range(0, min(len(rest), chunk * 4), chunk):
        piece = rest[i : i + chunk]
        if len(piece) < 8000:
            break
        text, _lang = transcribe_pcm(piece, hint_language="te-IN")
        if (text or "").strip():
            out.append(text.strip())
    return out


def _grade_pool_faq(lang: str, knowledge_rev: str, grades: dict, answer_stt: list[str]) -> dict:
    know = KNOWLEDGE_REV[knowledge_rev]
    time_token = "8:30" if knowledge_rev == "v1" else "6:00"
    agent_blob = " ".join(grades.get("agent_turns") or []).lower()
    stt_blob = " ".join(answer_stt).lower()
    heated_ok = any(
        x in agent_blob or x in stt_blob
        for x in ("లేదు", "not in", "नहीं", "not listed", "no spa", "మా", "दस्तावेज")
    )
    time_ok = (time_token.lower() in agent_blob) or (time_token in stt_blob) or (
        "8:30" in agent_blob if knowledge_rev == "v1" else "6:00" in agent_blob or "6 " in agent_blob
    )
    no_hardcoded_7 = "7 am" not in agent_blob and "7:00" not in agent_blob
    return {
        "time_from_doc": time_ok,
        "heated_missing": heated_ok,
        "not_hardcoded_7am": no_hardcoded_7,
        "n_user_turns": grades.get("n_user", 0),
        "pass": grades.get("n_user", 0) >= 2 and time_ok and heated_ok and no_hardcoded_7,
        "doc_expect": time_token,
        "agent_text": grades.get("agent_turns"),
        "answer_stt": answer_stt,
    }


async def _send_pcm_burst(ws_conn, pcm: bytes, *, frame_sleep: float = 0.02) -> None:
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
        await asyncio.sleep(frame_sleep)


async def run_sarvam_session(
    *,
    base_url: str,
    call_id: UUID,
    lang: str,
    scenario: str,
    knowledge_rev: str,
    greeting_lull_s: float,
    out_dir: Path,
) -> dict:
    if websockets is None:
        return {"ok": False, "error": "websockets_missing"}

    bcp47 = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}[lang]
    questions = _questions_for(lang, scenario)
    url = f"{base_url.rstrip('/')}/v1/ws/exotel/voice/{call_id}"
    recv_log: list[dict] = []
    t0 = time.monotonic()
    first_agent_media_at: float | None = None

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

        async def reader():
            nonlocal first_agent_media_at
            while True:
                try:
                    raw = await ws_conn.recv()
                except Exception:
                    break
                msg = json.loads(raw)
                recv_log.append(msg)
                if first_agent_media_at is None and msg.get("event") == "media":
                    first_agent_media_at = time.monotonic()

        read_task = asyncio.create_task(reader())
        greet_deadline = time.monotonic() + 18.0
        while time.monotonic() < greet_deadline:
            await asyncio.sleep(0.25)
            pcm_so_far = _decode_outbound_pcm(recv_log)
            if len(pcm_so_far) >= 55000:
                break
        await asyncio.sleep(max(0.35 if lang == "hi" else 0.1, greeting_lull_s))

        if scenario == "lang-echo":
            for text, _tag in LANG_ECHO_SEQUENCE:
                pcm = _tts_utterance_pcm(text, "te-IN" if "te" in text or "\u0c00" <= text[0] <= "\u0c7f" else "hi-IN")
                await _send_pcm_burst(ws_conn, pcm)
                await asyncio.sleep(2.4 if _tag == "reject_echo" else 3.0)
        else:
            for qi, qtext in enumerate(questions):
                pcm = _tts_utterance_pcm(qtext, bcp47)
                await _send_pcm_burst(ws_conn, pcm)
                # Let silence loop close the utterance before the next question or agent reply.
                pause = 7.5 if lang == "hi" else (4.8 if qi == 0 else 5.2)
                await asyncio.sleep(pause)

        await asyncio.sleep(5.5)
        await ws_conn.send(json.dumps({"event": "stop"}))
        await asyncio.sleep(0.5)
        read_task.cancel()

    pcm_out = _decode_outbound_pcm(recv_log)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / f"graded_{lang}_{call_id.hex[:8]}.wav"
    if pcm_out:
        import wave

        with wave.open(str(wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(pcm_out)

    grades = _load_call_grades(call_id)
    answer_stt = _transcribe_answer_snippets(pcm_out) if pcm_out else []
    result = {
        "lang": lang,
        "scenario": scenario,
        "knowledge_rev": knowledge_rev,
        "call_id": str(call_id),
        "elapsed_s": round(time.monotonic() - t0, 2),
        "outbound_pcm_bytes": len(pcm_out),
        "grades": grades,
        "answer_stt_snippets": answer_stt,
        "wav": str(wav) if pcm_out else "",
    }
    if scenario == "pool-faq":
        result["grade"] = _grade_pool_faq(lang, knowledge_rev, grades, answer_stt)
        result["ok"] = bool(result["grade"]["pass"])
    elif scenario == "lang-echo":
        result["ok"] = grades.get("n_user", 0) >= 1 and any(
            "फीस" in u or "fee" in u.lower() for u in grades.get("user_turns", [])
        ) or grades.get("n_user", 0) >= 2
        result["grade"] = {
            "echo_not_saved_as_only_turn": grades.get("n_user", 0) != 1
            or "फीस" in " ".join(grades.get("user_turns", [])),
            "agent_turns": grades.get("agent_turns"),
        }
    else:
        result["ok"] = grades.get("n_user", 0) >= 2 and len(pcm_out) > 16_000
    return result


async def main_async(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    results: list[dict] = []
    fails = 0

    if args.scenario == "lang-echo":
        cid = _create_call(
            knowledge=KNOWLEDGE_REV["v1"],
            employee_lang="Telugu",
            revision="echo-test",
        )
        r = await run_sarvam_session(
            base_url=args.base_url,
            call_id=cid,
            lang="te",
            scenario="lang-echo",
            knowledge_rev="v1",
            greeting_lull_s=args.greeting_lull,
            out_dir=out_dir,
        )
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        summary = out_dir / "graded_replay_summary.json"
        summary.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"summary -> {summary}")
        return 0 if r.get("ok") else 1

    for lang in args.langs:
        emp_lang = {"te": "Telugu", "hi": "Hindi", "en": "English"}[lang]
        cid = _create_call(
            knowledge=KNOWLEDGE_REV[args.knowledge_rev],
            employee_lang=emp_lang,
            revision=args.knowledge_rev,
        )
        r = await run_sarvam_session(
            base_url=args.base_url,
            call_id=cid,
            lang=lang,
            scenario=args.scenario,
            knowledge_rev=args.knowledge_rev,
            greeting_lull_s=args.greeting_lull,
            out_dir=out_dir,
        )
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if not r.get("ok"):
            fails += 1

    if args.revision_rerun and args.scenario == "pool-faq":
        rev = "v2" if args.knowledge_rev == "v1" else "v1"
        lang = args.langs[0]
        emp_lang = {"te": "Telugu", "hi": "Hindi", "en": "English"}[lang]
        cid2 = _create_call(knowledge=KNOWLEDGE_REV[rev], employee_lang=emp_lang, revision=rev)
        r2 = await run_sarvam_session(
            base_url=args.base_url,
            call_id=cid2,
            lang=lang,
            scenario="pool-faq",
            knowledge_rev=rev,
            greeting_lull_s=args.greeting_lull,
            out_dir=out_dir,
        )
        results.append(r2)
        print(json.dumps(r2, ensure_ascii=False, indent=2))
        if not r2.get("ok"):
            fails += 1

    summary = out_dir / "graded_replay_summary.json"
    summary.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"summary -> {summary}")
    return fails


def main() -> int:
    p = argparse.ArgumentParser(description="Graded Sarvam Exotel WS replay")
    p.add_argument("--langs", default="te", help="Comma-separated te,hi,en")
    p.add_argument(
        "--base-url",
        default=os.environ.get("EXOTEL_REPLAY_WS", "ws://127.0.0.1:8010"),
    )
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "tmp", "exotel_replay"))
    p.add_argument("--scenario", choices=("pool-faq", "default", "lang-echo"), default="pool-faq")
    p.add_argument("--knowledge-rev", choices=("v1", "v2"), default="v1")
    p.add_argument("--greeting-lull", type=float, default=0.15, help="Seconds after first agent audio before Q1")
    p.add_argument("--revision-rerun", action="store_true", help="Second session with other knowledge rev")
    args = p.parse_args()
    args.langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())