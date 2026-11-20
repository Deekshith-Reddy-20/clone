"""Sarvam Bulbul v3 preview voices for browser test calls."""

from __future__ import annotations

from typing import Literal

VoiceGender = Literal["female", "male"]

PREVIEW_VOICES: tuple[dict[str, str], ...] = (
    {
        "id": "priya",
        "label": "Priya",
        "gender": "female",
        "hint": "Warm, clear Telugu/Hindi/English",
    },
    {
        "id": "neha",
        "label": "Neha",
        "gender": "female",
        "hint": "Friendly conversational tone",
    },
    {
        "id": "shubh",
        "label": "Shubh",
        "gender": "male",
        "hint": "Default phone voice — steady pace",
    },
    {
        "id": "aditya",
        "label": "Aditya",
        "gender": "male",
        "hint": "Professional support style",
    },
)

DEFAULT_PREVIEW_SPEAKER = "shubh"


def is_valid_preview_speaker(speaker_id: str) -> bool:
    sid = (speaker_id or "").strip().lower()
    return any(v["id"] == sid for v in PREVIEW_VOICES)


def resolve_tts_speaker(speaker_id: str | None, *, gender_preference: str | None = None) -> str:
    """Map saved hire/preview choice to a supported Bulbul speaker id."""
    sid = (speaker_id or "").strip().lower()
    if is_valid_preview_speaker(sid):
        return sid
    g = (gender_preference or "").strip().lower()
    if g == "female":
        return "priya"
    if g == "male":
        return DEFAULT_PREVIEW_SPEAKER
    return DEFAULT_PREVIEW_SPEAKER


_BULBUL_V4_PERSONA: dict[tuple[str, str], str] = {
    ("shubh", "te-IN"): "tarun_te_narration",
    ("shubh", "hi-IN"): "shubh_hi_customer",
    ("shubh", "en-IN"): "simran_en_conversation",
    ("priya", "te-IN"): "pooja_te_conversation",
    ("priya", "hi-IN"): "priya_hi_recovery",
    ("priya", "en-IN"): "neha_en_customer",
    ("neha", "te-IN"): "pooja_te_conversation",
    ("neha", "hi-IN"): "ritu_hi_customer",
    ("neha", "en-IN"): "neha_en_customer",
    ("aditya", "te-IN"): "tarun_te_narration",
    ("aditya", "hi-IN"): "aditya_hi_conversational",
    ("aditya", "en-IN"): "dev_en_conversational",
}


def resolve_bulbul_speaker_for_lang(
    speaker_id: str | None,
    lang_bcp47: str,
    *,
    tts_model: str = "bulbul:v4-flash",
) -> str:
    """UI uses shubh/priya; Bulbul v4-flash needs persona ids per language."""
    spk = resolve_tts_speaker(speaker_id)
    lang = (lang_bcp47 or "en-IN").strip()
    if lang not in ("te-IN", "hi-IN", "en-IN"):
        lang = "en-IN"
    if tts_model != "bulbul:v4-flash":
        return spk
    return _BULBUL_V4_PERSONA.get((spk, lang)) or {
        "te-IN": "tarun_te_narration",
        "hi-IN": "shubh_hi_customer",
        "en-IN": "simran_en_conversation",
    }[lang]


def speaker_gender_label(speaker_id: str) -> str:
    sid = (speaker_id or "").strip().lower()
    for v in PREVIEW_VOICES:
        if v["id"] == sid:
            return v["gender"]
    return ""