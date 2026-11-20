"""karyuk-m05 phone agent, spoken through Sarvam instead of Gemini Live.

The instructions, fact sheet, and opening line come from the m05 voice agent
(``build_phone_session_material``). Audio stays on the existing Exotel session:
Saaras STT, Sarvam 105B chat, Bulbul TTS.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from app.services.voice.sarvam import complete_chat
from app.services.voice.spoken_output import filter_caller_facing_reply

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_INSTRUCTIONS: dict[str, str] = {}
_READY = False

_LIVE_TURN = (
    "You are on the live phone call now. The opening line was already spoken; "
    "do not repeat it unless the caller asks who you are. "
    "Say only the words the caller should hear. No headings, markdown, or fact-sheet labels."
)


def m05_root() -> Path:
    raw = os.getenv("KARYUK_M05_ROOT", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4].parent / "karyuk-m05"


def team_employee_voice_active(fields: dict | None) -> bool:
    """Published/draft Your Team employee is pinned on this call — never use legacy m05."""
    if not fields:
        return False
    brief = (fields.get("employee_brief") or "").strip()
    know = (fields.get("employee_website_knowledge") or "").strip()
    if fields.get("knowledge_state") in ("published", "draft"):
        return bool(brief or know)
    if fields.get("employee_snapshot_revision"):
        return True
    return len(brief) >= 16 or len(know) >= 48


def m05_voice_enabled(*, call_fields: dict | None = None) -> bool:
    """True when this process should answer as the legacy m05 phone agent (not Team employees)."""
    if team_employee_voice_active(call_fields):
        return False
    flag = os.getenv("KARYUK_VOICE_AGENT", "").strip().lower()
    if not flag:
        flag = os.getenv("VOICE_AGENT_PROFILE", "").strip().lower()
    if flag in {"0", "false", "off", "employee", "cc"}:
        return False
    if flag in {"1", "true", "on", "m05", "karyuk-m05", "anitha"}:
        return True
    if "unittest" in sys.modules:
        return False
    from app.config import get_settings

    profile = (get_settings().voice_agent_profile or "employee").strip().lower()
    return profile not in {"employee", "cc", "0", "false", "off"}


def employee_lang_code(raw: str | None) -> str:
    n = (raw or "").strip().lower()
    if "hindi" in n or n in {"hi", "hi-in"}:
        return "hi"
    if "english" in n or n in {"en", "en-in"}:
        return "en"
    if "telugu" in n or n in {"te", "te-in"}:
        return "te"
    return "te"


def _ensure_m05_path() -> None:
    global _READY
    root = m05_root()
    voice = root / "voice_agent"
    src = root / "src"
    if not (voice / "karyuk_voice").is_dir():
        raise RuntimeError(f"karyuk-m05 voice agent not found at {voice}")
    for entry in (str(voice), str(src)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    _READY = True


def spoken_opening(employee_language: str | None) -> str:
    """The exact opening line the m05 agent speaks, not the model trigger."""
    _ensure_m05_path()
    from karyuk_voice.phone_opening import build_phone_opening_trigger

    code = employee_lang_code(employee_language)
    trigger = build_phone_opening_trigger(code)
    line = trigger.rsplit(": ", 1)[-1].strip()
    return line or trigger.strip()


def phone_instructions(employee_language: str | None) -> str:
    """Same system instructions the m05 Exotel agent sends to Gemini Live."""
    code = employee_lang_code(employee_language)
    with _LOCK:
        cached = _INSTRUCTIONS.get(code)
        if cached:
            return cached
        _ensure_m05_path()
        os.environ["KARYUK_EMPLOYEE_LANGUAGE"] = code
        os.environ.setdefault("KARYUK_EMPLOYEE_ROLE", "receptionist")
        from karyuk_voice.phone_context import build_phone_session_material

        instructions, _tools, _greet, _document, _source, _state = build_phone_session_material()
        text = (instructions or "").strip()
        if not text:
            raise RuntimeError("m05 phone instructions were empty")
        _INSTRUCTIONS[code] = text
        return text


def generate_m05_reply(
    *,
    caller_text: str,
    history: list[dict[str, str]],
    reply_language: str,
    employee_language: str | None,
) -> str | None:
    """Sarvam chat reply using the m05 phone prompt. None if the agent cannot load."""
    lang_name = {"te-IN": "Telugu", "hi-IN": "Hindi", "en-IN": "Indian English"}.get(
        reply_language, "Telugu"
    )
    try:
        instructions = phone_instructions(employee_language)
    except Exception:
        logger.exception("m05_phone_material_failed")
        return None

    messages: list[dict[str, str]] = [
        {"role": "system", "content": f"{instructions}\n\n{_LIVE_TURN}"},
    ]
    for turn in history[-8:]:
        role = turn.get("role")
        content = (turn.get("text") or "")[:500]
        if role == "user" and content:
            messages.append({"role": "user", "content": content})
        elif role == "assistant" and content:
            messages.append({"role": "assistant", "content": content})
    user = (caller_text or "").strip() or "Hello"
    messages.append(
        {
            "role": "user",
            "content": f"(Reply in {lang_name} only, one or two short spoken sentences.)\n{user[:500]}",
        }
    )
    raw = complete_chat(messages, max_tokens=180, temperature=0.4)
    if not raw:
        return None
    reply = filter_caller_facing_reply(raw, lang=reply_language)
    return reply[:400] if reply else None
