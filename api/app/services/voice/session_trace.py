"""Redacted per-session voice trace (no secrets, full numbers, or raw transcripts)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("karyuk.voice_trace")
Channel = Literal["browser", "exotel"]


def _build_sha() -> str:
    env = (os.getenv("KARYUK_VOICE_BUILD_SHA") or "").strip()
    if env:
        return env[:12]
    root = Path(__file__).resolve().parents[3]
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()[:12]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def mask_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"+***{digits[-4:]}"


def knowledge_revision_from_fields(fields: dict | None) -> str:
    if not fields:
        return "none"
    rev = str(fields.get("employee_snapshot_revision") or "").strip()
    if rev:
        return rev[:32]
    blob = json.dumps(
        {
            "brief_len": len(str(fields.get("employee_brief") or "")),
            "web_len": len(str(fields.get("employee_website_knowledge") or "")),
            "emp": str(fields.get("employee_language") or ""),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def emit_voice_session_trace(
    *,
    channel: Channel,
    call_id: str,
    locale_bcp47: str,
    speech_stack: str,
    stt_model: str,
    tts_voice_requested: str,
    tts_voice_confirmed: str | None,
    conversation_policy_version: str | None = None,
    knowledge_revision: str,
    knowledge_state: str,
    audio_flags: dict[str, Any] | None = None,
    call_meta: dict | None = None,
) -> dict[str, Any]:
    from app.services.voice.spoken_policy import CONVERSATION_POLICY_VERSION

    policy_ver = conversation_policy_version or CONVERSATION_POLICY_VERSION
    trace = {
        "trace_id": str(uuid.uuid4()),
        "ts": time.time(),
        "channel": channel,
        "worker": "karyuk-cc-uvicorn",
        "build_sha": _build_sha(),
        "session_id": call_id,
        "locale_bcp47": locale_bcp47,
        "speech_stack": speech_stack,
        "stt_model_requested": stt_model,
        "tts_voice_requested": tts_voice_requested,
        "tts_voice_confirmed": tts_voice_confirmed or "requested_not_confirmed",
        "spoken_policy_version": policy_ver,
        "knowledge_revision": knowledge_revision,
        "knowledge_state": knowledge_state,
        "grounding_mode": "employee_snapshot",
        "audio_processing": audio_flags or {},
    }
    if call_meta:
        trace["call"] = {
            "stream_sid_prefix": (str(call_meta.get("stream_sid") or ""))[:8],
            "from_masked": mask_phone(str(call_meta.get("from") or "")),
            "to_masked": mask_phone(str(call_meta.get("to") or "")),
        }
    logger.info("session_trace %s", json.dumps(trace, default=str))
    return trace


def log_voice_turn(
    *,
    call_id: str,
    turn_index: int,
    inbound_media_chunks: int,
    greeting_done: bool,
    listening: int,
    stt_text_len: int,
    stt_lang: str,
    conv_lang: str,
    knowledge_revision: str,
    reply_pcm_bytes: int = 0,
    reply_audio_sent: int = 0,
    lookup: str = "",
    drop_reason: str = "",
    think_ms: int = 0,
) -> None:
    """Redacted per-turn trace — lengths and flags only, no transcripts or secrets."""
    logger.info(
        "voice_turn %s",
        json.dumps(
            {
                "call_id_prefix": call_id[:8],
                "turn": turn_index,
                "inbound_media_chunks": inbound_media_chunks,
                "greeting_done": greeting_done,
                "listening": listening,
                "stt_text_len": stt_text_len,
                "stt_lang": stt_lang,
                "conv_lang": conv_lang,
                "knowledge_revision": knowledge_revision[:16] if knowledge_revision else "",
                "lookup": lookup or None,
                "reply_pcm_bytes": reply_pcm_bytes,
                "reply_audio_sent": reply_audio_sent,
                "drop_reason": drop_reason or None,
                "think_ms": think_ms,
            },
            default=str,
        ),
    )


def log_pipeline_event(
    *,
    call_id: str,
    stage: str,
    **fields: Any,
) -> None:
    """Redacted pipeline milestones — no audio, transcripts, phones, or secrets."""
    payload = {
        "call_id_prefix": call_id[:8],
        "stage": stage,
        **{k: v for k, v in fields.items() if v is not None},
    }
    logger.info("voice_pipeline %s", json.dumps(payload, default=str))


def log_turn_decision(
    *,
    call_id: str,
    accepted: bool,
    reason: str,
    locale_bcp47: str,
    text_len: int,
    speech_stack: str = "sarvam",
) -> None:
    logger.info(
        "turn_decision %s",
        json.dumps(
            {
                "call_id_prefix": call_id[:8],
                "accepted": accepted,
                "reason": reason,
                "locale_bcp47": locale_bcp47,
                "text_len": text_len,
                "speech_stack": speech_stack,
            }
        ),
    )