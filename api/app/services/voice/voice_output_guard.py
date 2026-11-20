"""Reject LLM replies that leak instructions or fail spoken-style rules."""

from __future__ import annotations

import re

from app.services.voice.spoken_output import looks_like_private_leak
from app.services.voice.voice_facts import split_brief_instructions_and_facts


_BLOCKED_PHRASES = (
    "your name is",
    "you are maya",
    "you are ",
    "use the live booking system",
    "as an ai language model",
    "knowledge base",
    "instructions",
    "internal playbook",
    "గురించి:",
    "v farms / v-form గురించి",
    "fact:",
    "tools:",
)


def _has_markdown(text: str) -> bool:
    return bool(
        re.search(r"^[\s]*[-*#|]", text, re.M)
        or "**" in text
        or "__" in text
    )


def _copied_from_instructions(reply: str, instructions: str) -> bool:
    r = (reply or "").lower()
    for chunk in re.split(r"[\n.]+", instructions or ""):
        words = chunk.strip().split()
        if len(words) >= 8 and chunk.strip().lower() in r:
            return True
    return False


def _word_count(text: str) -> int:
    return len((text or "").split())


def _sentence_count(text: str) -> int:
    parts = re.findall(r"[^.!?।]+[.!?।]?", (text or "").strip())
    return len([p for p in parts if p.strip()])


def _too_similar_to_last(reply: str, last: str) -> bool:
    if not last or not reply:
        return False
    a = set(reply.lower().split())
    b = set(last.lower().split())
    if len(a) < 6:
        return False
    overlap = len(a & b) / max(len(a), 1)
    return overlap > 0.72


def guard_reply_rejected(
    reply: str,
    *,
    brief: str,
    lang: str,
    last_agent_reply: str | None = None,
) -> tuple[str, bool]:
    """Returns (possibly cleaned reply, rejected). If rejected, reply should not be spoken."""
    t = (reply or "").strip()
    if not t:
        return "", True
    if looks_like_private_leak(t):
        return t, True
    low = t.lower()
    if any(p in low for p in _BLOCKED_PHRASES):
        return t, True
    if _has_markdown(t):
        return t, True
    if re.search(r"https?://|www\.", low):
        return t, True
    inst, _ = split_brief_instructions_and_facts(brief)
    if _copied_from_instructions(t, inst):
        return t, True
    if _word_count(t) > 32:
        return t, True
    if _sentence_count(t) > 2:
        return t, True
    if last_agent_reply and _too_similar_to_last(t, last_agent_reply):
        return t, True
    return t, False


def llm_hard_fallback(lang: str) -> str:
    if lang == "te-IN":
        return "క్షమించండి అండి, ఒక్క క్షణం — మీ ప్రశ్నకు సరైన సమాధానం చూస్తాను."
    if lang == "hi-IN":
        return "माफ़ कीजिए जी, एक पल — मैं सही जानकारी देखती हूँ।"
    return "Sorry — one moment while I get the right information for you."