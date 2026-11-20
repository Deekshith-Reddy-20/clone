"""Per-sentence guard before PSTN TTS."""

from __future__ import annotations

from app.services.voice.voice_fact_guard import reply_invented_negative
from app.services.voice.voice_grounding_guard import (
    confirm_save_lead_line,
    sentence_fails_grounding,
)
from app.services.voice.voice_output_guard import guard_reply_rejected
from app.services.voice.spoken_length import enforce_brevity
from app.services.voice.spoken_output import filter_caller_facing_reply
from app.services.voice.sarvam import sanitize_reply_for_lang


def guard_stream_sentence(
    sentence: str,
    *,
    brief: str,
    lang: str,
    vertical: str,
    spoken_facts: str,
    caller_text: str,
    fields: dict,
    last_agent_reply: str | None = None,
) -> tuple[str | None, list[str]]:
    """Return (safe_to_speak, action_tags). None = drop sentence."""
    actions: list[str] = []
    t = filter_caller_facing_reply((sentence or "").strip(), lang=lang)
    if not t:
        return None, ["empty"]
    t = sanitize_reply_for_lang(t, lang, vertical=vertical)
    trimmed, needs_regen = enforce_brevity(t)
    if needs_regen:
        actions.append("brevity_fail")
        return None, actions
    t = trimmed
    t, rejected = guard_reply_rejected(
        t, brief=brief, lang=lang, last_agent_reply=last_agent_reply
    )
    if rejected:
        actions.append("output_guard")
        return None, actions
    if reply_invented_negative(t, spoken_facts):
        actions.append("invented_negative")
        return None, actions
    fail, reasons = sentence_fails_grounding(
        t, spoken_facts=spoken_facts, fields=fields, caller_text=caller_text
    )
    if fail:
        actions.extend(reasons)
        return None, actions
    return t, actions


def replacement_for_guard_fail(
    *,
    lang: str,
    actions: list[str],
    caller_text: str,
    spoken_facts: str,
) -> str:
    del caller_text, spoken_facts
    if actions:
        return confirm_save_lead_line(lang)
    return confirm_save_lead_line(lang)