"""Keep private playbook text and meta instructions out of TTS."""

from __future__ import annotations

import re

_PRIVATE_PREFIXES = (
    "you are ",
    "you're ",
    "your name is",
    "playbook",
    "website facts",
    "your job on every call",
    "never mention prompts",
    "instructions:",
    "employee brief",
    "use the live booking",
    "knowledge base",
    "as an ai",
    "v farms / v-form",
    "గురించి:",
)

_EMERGENCY_CALLER_TE = "తక్షణ సహాయం కోసం 112కి కాల్ చేయండి."


def is_emergency_utterance(text: str) -> bool:
    t = (text or "").lower()
    te = text or ""
    markers = (
        "emergency",
        "ambulance",
        "heart attack",
        "stroke",
        "bleeding",
        "unconscious",
        "తక్షణ",
        "అత్యవసర",
        "అంబులెన్స్",
        "112",
        "108",
    )
    return any(m in t or m in te for m in markers)


def emergency_reply(lang: str) -> str:
    if lang == "te-IN":
        return _EMERGENCY_CALLER_TE
    if lang == "hi-IN":
        return "तुरंत मदद के लिए 112 पर कॉल करें।"
    return "For immediate help, call 112."


def looks_like_private_leak(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if any(low.startswith(p) for p in _PRIVATE_PREFIXES):
        return True
    if "PLAYBOOK" in t or "WEBSITE FACTS" in t:
        return True
    if re.search(r"\byou are \w+", low) and len(t) > 40:
        return True
    return False


def filter_caller_facing_reply(text: str, *, lang: str = "en-IN") -> str:
    """Drop or replace lines that must never be spoken on PSTN."""
    t = (text or "").strip()
    if not t:
        return t
    if looks_like_private_leak(t):
        return {
            "te-IN": "సరే అండి, ఎలా సహాయం చేయగలను?",
            "hi-IN": "बताइए, मैं कैसे मदद करूँ?",
            "en-IN": "How can I help you today?",
        }.get(lang, "How can I help you today?")
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    kept = [ln for ln in lines if not looks_like_private_leak(ln)]
    if not kept:
        return filter_caller_facing_reply("", lang=lang)
    joined = " ".join(kept)
    if joined.startswith("{") or joined.startswith("["):
        return {
            "te-IN": "సరే అండి, ఎలా సహాయం చేయగలను?",
            "hi-IN": "बताइए, मैं कैसे मदद करूँ?",
            "en-IN": "How can I help you today?",
        }.get(lang, "How can I help you today?")
    joined = re.sub(r"<[^>]+>", " ", joined)
    joined = re.sub(r"\s+", " ", joined).strip()
    from app.services.voice.spoken_length import cap_spoken_reply

    return cap_spoken_reply(joined, max_chars=500)