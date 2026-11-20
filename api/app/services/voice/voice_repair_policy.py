"""When STT/LLM/tools fail — never repeat the same repair line twice."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.voice.booking_state import load_booking
from app.services.voice.sarvam import _clarify_more
from app.services.owner_notify import load_workspace_owner, manager_callback_minutes


def is_frustration_utterance(text: str) -> bool:
    t = (text or "").strip()
    low = t.lower()
    return any(
        p in t or p in low
        for p in (
            "అర్థం కాలే",
            "అర్థం కాలేదు",
            "ఓసేయ్",
            "చాలా సార్లు",
            "మరోసారి చెప్ప",
            "what should i say",
            "does not make sense",
            "stupid",
            "idiot",
        )
    )


def repair_line(lang: str) -> str:
    return _clarify_more(lang)


def _callback_phrase(lang: str, db: Session | None, workspace_id: UUID | None) -> str:
    if not db or not workspace_id:
        return (
            "మా team త్వరలో call చేస్తారు అండి."
            if lang == "te-IN"
            else "Our team will call you back soon."
        )
    wo, contacts = load_workspace_owner(db, workspace_id)
    mins = manager_callback_minutes(wo, contacts)
    if mins:
        return (
            f"మా team {mins} నిమిషాల్లో confirm చేసి call చేస్తారు అండి."
            if lang == "te-IN"
            else f"Our team will confirm and call you within {mins} minutes."
        )
    return (
        "మా team త్వరలో call చేస్తారు అండి."
        if lang == "te-IN"
        else "Our team will call you back soon."
    )


def pick_repair_reply(
    *,
    lang: str,
    caller_text: str,
    fields: dict,
    turns: list[dict[str, str]],
    last_agent: str | None,
    reason: str = "unknown",
    db: Session | None = None,
    workspace_id: UUID | None = None,
) -> str:
    """Escalate repair prompts; never duplicate previous assistant line."""
    streak = int(fields.get("repair_streak") or 0)
    if last_agent and repair_line(lang).strip() in (last_agent or "").strip():
        streak += 1
    else:
        streak = 1 if repair_line(lang) in (last_agent or "") else streak
    fields["repair_streak"] = streak
    fields["last_repair_reason"] = reason

    st = load_booking(fields)
    cb = _callback_phrase(lang, db, workspace_id)
    if is_frustration_utterance(caller_text) or streak >= 3:
        cin = st.check_in or "?"
        guests = st.guest_count or "?"
        if lang == "te-IN":
            return (
                f"క్షమించండి అండి — confusion అయింది. {cin} check-in, {guests} guests నోట్ చేశాను. {cb}"
            )
        return (
            f"Sorry for the confusion. I noted check-in {cin}, {guests} guests. {cb}"
        )

    if streak == 2:
        if lang == "te-IN":
            if st.guest_count:
                return f"guests ఎంతమంది అండి — {st.guest_count} అన్నారా? check-in {st.check_in or 'తేదీ'} సరేనా?"
            return f"check-in {st.check_in or 'ఏ తేదీ'} నేనా? check-out లేకుంటే రాత్రులు ఎన్ని?"
        return "Could you confirm the check-in date and number of guests?"

    return repair_line(lang)


def frustration_closing(
    *,
    lang: str,
    fields: dict,
    db: Session | None = None,
    workspace_id: UUID | None = None,
) -> str:
    st = load_booking(fields)
    cin = st.check_in or "?"
    guests = st.guest_count or "?"
    cb = _callback_phrase(lang, db, workspace_id)
    if lang == "te-IN":
        return (
            f"క్షమించండి అండి. {cin} check-in, {guests} guests — booking request note చేశాను. {cb}"
        )
    return f"Sorry — I noted {cin} check-in, {guests} guests. Booking request noted. {cb}"


def llm_closing_instruction(lang: str) -> str:
    if lang == "te-IN":
        return (
            "[closing: Call is long. In Telugu only — apologize briefly, state booking outcome from call_state, "
            "thank them. Max 2 sentences. Do not say goodbye in English.]"
        )
    return "[closing: Summarize booking outcome from call_state, 2 sentences max, caller language only.]"