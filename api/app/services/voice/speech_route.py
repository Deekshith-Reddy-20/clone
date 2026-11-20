"""Locale → speech stack for PSTN (Exotel). te / hi / en-IN all use Sarvam STT + TTS + chat."""

from __future__ import annotations

import re
from typing import Literal

from app.services.voice.sarvam import (
    SUPPORTED_BCP47,
    clamp_voice_lang,
    detect_language_from_text,
    language_bcp47_from_employee,
)

SpeechStack = Literal["sarvam"]

_TELUGU_SWITCH = re.compile(
    r"(తెలుగు|telugu|telugulo|తెలుగులో|matladagalar)",
    re.I,
)
_HINDI_SWITCH = re.compile(
    r"(हिंदी|हिन्दी|hindi|hindi mein|हिंदी में)",
    re.I,
)
_ENGLISH_SWITCH = re.compile(
    r"(english please|speak english|in english only)",
    re.I,
)


def speech_stack_for_bcp47(bcp47: str) -> SpeechStack:
    clamp_voice_lang(bcp47, "en-IN")
    return "sarvam"


def resolve_conversation_bcp47(
    *,
    caller_text: str,
    conversation_language: str | None,
    employee_language: str | None,
) -> str:
    from app.services.voice.sarvam import resolve_call_language

    return resolve_call_language(
        caller_text=caller_text,
        conversation_language=conversation_language,
        employee_language=employee_language,
        stt_language=None,
    )


def apply_explicit_language_switch(caller_text: str, current: str | None) -> str | None:
    t = (caller_text or "").strip()
    if _TELUGU_SWITCH.search(t):
        return "te-IN"
    if _HINDI_SWITCH.search(t):
        return "hi-IN"
    if _ENGLISH_SWITCH.search(t):
        return "en-IN"
    if len(t) >= 24:
        detected = detect_language_from_text(t)
        if detected in SUPPORTED_BCP47:
            return detected
    return current


def stack_after_switch(bcp47: str) -> SpeechStack:
    return speech_stack_for_bcp47(bcp47)


def employee_default_bcp47(employee_language: str | None) -> str:
    return clamp_voice_lang(language_bcp47_from_employee(employee_language or ""), "en-IN")