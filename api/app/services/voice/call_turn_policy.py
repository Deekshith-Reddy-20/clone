"""Accept/reject caller turns on PSTN — noise vs real questions."""

from __future__ import annotations

import re

from app.services.voice.sarvam import (
    _has_devanagari_script,
    _has_telugu_script,
    detect_language_from_text,
    is_hindi_ack_noise,
    is_real_hindi_question,
    is_spurious_stt_snippet,
    language_bcp47_from_employee,
)

_TELUGU_SHORT_ACK = frozenset(
    {
        "అవును",
        "సరే",
        "అవున",
        "హా",
        "ఆ",
        "చెప్పండి",
        "కాదు",
        "లేదు",
    }
)

_HINDI_SHORT_ACK = frozenset({"हाँ", "हां", "जी", "ठीक", "नहीं", "हाँ जी", "हां जी"})

_ENGLISH_SHORT_ACK = frozenset(
    {
        "yes",
        "no",
        "ok",
        "okay",
        "yeah",
        "yep",
        "nope",
        "sure",
        "right",
        "correct",
        "fine",
        "done",
        "haan",
        "ha",
        "ji",
        "please",
    }
)


def employee_bcp47(employee_language: str | None) -> str:
    return language_bcp47_from_employee(employee_language or "")


def is_short_acknowledgment(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    low = t.lower().strip(".,!? ")
    if t in _TELUGU_SHORT_ACK:
        return True
    if t in _HINDI_SHORT_ACK or low in _ENGLISH_SHORT_ACK:
        return True
    if re.fullmatch(r"\d{1,2}", t):
        return True
    if any(p in t for p in ("ఆ అంతే", "book చేయండి", "సరే", "yes confirm", "okay book")):
        return True
    return len(t) <= 8 and _has_telugu_script(t)


def is_booking_slot_turn(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if re.fullmatch(r"\d{1,2}", t):
        return True
    if re.search(r"\d", t) and len(t) <= 48:
        return True
    if re.search(
        r"(వస్తారు|మంది|guests?|members?|గురం|నలుగురు|ఎల్లుండి|రేపు|check.?in|book|rooms?|"
        r"గది|గదులు|పూల్|pool|available|ఉన్నాయా|ఉందా)",
        t,
        re.I,
    ):
        return True
    return is_short_acknowledgment(t)


def reject_turn_reason(
    text: str,
    *,
    employee_language: str | None,
    conversation_language: str | None = None,
) -> str | None:
    """None = process turn; else log reason and skip TTS."""
    t = (text or "").strip()
    if not t:
        return "empty"
    if is_spurious_stt_snippet(t):
        return "spurious"
    if is_hindi_ack_noise(t):
        return "hindi_ack_noise"
    if is_short_acknowledgment(t):
        return None
    if is_booking_slot_turn(t):
        return None
    if len(t) < 2 and not _has_telugu_script(t):
        return "too_short"
    # 1–3 char STT crumbs (often echo leftovers) — ignore unless ack/digit/booking.
    if len(t) <= 3 and not is_short_acknowledgment(t) and not re.search(r"\d", t):
        return "too_short"

    emp = employee_bcp47(employee_language)
    has_te = _has_telugu_script(t)
    has_hi = _has_devanagari_script(t)
    conv = (conversation_language or "").strip() or emp

    if emp == "te-IN" and has_hi and not has_te:
        if is_hindi_ack_noise(t):
            return "hindi_ack_noise"
        if len(t) < 28:
            if is_real_hindi_question(t):
                return None
            return "hindi_noise_telugu_line"
        low = t.lower()
        if low in ("hello", "hi", "hey") and len(t) < 10:
            return "english_ping"

    # Telugu speech is dense in characters — accept short real utterances.
    if has_te and len(t) >= 3:
        return None
    if len(t) >= 16 and not (emp == "te-IN" and has_hi and not has_te and len(t) < 28):
        return None
    if has_hi and len(t) >= 28:
        return None
    letters = [c for c in t if c.isalpha()]
    if len(letters) >= 5:
        latin = sum(1 for c in letters if ord(c) < 128)
        if latin / len(letters) > 0.85 and len(t) >= 5:
            # Mid-call English answers on a Telugu line (dates, "twenty two", etc.).
            if conv in ("te-IN", "hi-IN", "en-IN") and len(t) >= 5:
                return None
            if len(t) >= 10:
                return None
    if re.search(r"[a-zA-Z]{4,}", t):
        return None
    return "low_signal"


def stt_language_for_reply(
    transcript: str,
    stt_detected: str | None,
    *,
    employee_language: str | None,
    conversation_language: str | None,
) -> str | None:
    """Do not let Sarvam's lang tag alone flip Hindi on a Telugu employee."""
    if reject_turn_reason(
        transcript,
        employee_language=employee_language,
        conversation_language=conversation_language,
    ):
        return None
    from_text = detect_language_from_text(transcript)
    t = (transcript or "").strip()
    if from_text and len(t) >= 20:
        return from_text
    if len(t) >= 28 and _has_devanagari_script(t):
        return "hi-IN"
    return None