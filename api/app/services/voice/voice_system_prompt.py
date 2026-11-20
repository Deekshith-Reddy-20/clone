"""Render prompts/voice_agent_system.md for every inbound LLM call (Phase C)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.schemas.business_profile import BusinessProfile

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "voice_agent_system.md"
_TZ = ZoneInfo("Asia/Kolkata")

_PRIMARY_CTA = {
    "lodging": "room booking (dates and guests)",
    "resort": "room booking (dates and guests)",
    "real_estate": "site visit (date and time)",
    "college": "campus visit or admissions counselling",
    "hospital": "appointment scheduling",
    "general": "callback or next step from FACTS",
}

_VERTICAL_FOR_CTA = {
    "lodging": "resort",
    "hospital": "hospital",
}


def _load_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def primary_cta_for_vertical(vertical: str, business_type: str = "") -> str:
    bt = (business_type or "").strip().lower()
    if bt in _PRIMARY_CTA:
        return _PRIMARY_CTA[bt]
    v = _VERTICAL_FOR_CTA.get(vertical, vertical)
    return _PRIMARY_CTA.get(v, _PRIMARY_CTA["general"])


def _objection_block(profile: BusinessProfile | None) -> str:
    if not profile or not profile.objection_handling:
        return "Use USPs and offers from FACTS; never invent discounts."
    lines = []
    for item in profile.objection_handling[:8]:
        lines.append(f"- {item.objection}: {item.response_facts}")
    return "\n".join(lines)


def _no_repeat_hint(last_replies: list[str]) -> str:
    if not last_replies:
        return ""
    snippet = " | ".join(r[:120] for r in last_replies[-2:])
    return (
        "NO-REPEAT: Caller already heard this — add NEW detail (landmark, directions, "
        f"timing, price caveat), do not paraphrase the same answer.\nLast replies: {snippet}"
    )


def build_voice_system_prompt(
    *,
    persona_name: str,
    business_name: str,
    facts: str,
    reply_language: str,
    vertical: str,
    profile: dict | None = None,
    last_agent_replies: list[str] | None = None,
) -> str:
    p = BusinessProfile.from_snapshot(profile)
    business = p.business.name or business_name or "the business"
    persona = persona_name or "Maya"
    biz_type = p.business.type or _VERTICAL_FOR_CTA.get(vertical, vertical)
    cta = primary_cta_for_vertical(vertical, biz_type)
    from app.services.voice.voice_dates import calendar_block_for_prompt, today_local

    anchor = today_local()
    env_anchor = __import__("os").environ.get("KARYUK_CALL_DATE", "").strip()
    if env_anchor:
        try:
            anchor = date.fromisoformat(env_anchor[:10])
        except ValueError:
            pass
    now = datetime.now(_TZ).strftime("%A, %d %B %Y %H:%M %Z")
    cal = calendar_block_for_prompt(anchor=anchor)

    lang_rules = {
        "te-IN": "Telugu-English codemix as the caller; use అండి naturally; max 30 words.",
        "hi-IN": "Hindi with जी/आप; max 30 words.",
        "en-IN": "Indian English; switch fully to English if caller uses English only; max 30 words.",
    }.get(reply_language, "Match caller language; max 30 words.")

    template = _load_template()
    body = template.format(
        persona_name=persona,
        business_name=business,
        facts=(facts or "No published facts — offer callback only.").strip()[:5200],
        primary_cta=cta,
        date_local=now,
    )
    few_shot = """
FEW-SHOT (unknown fact → brief confirm + save_lead same turn):
1) Caller: హెలిప్యాడ్ ఉందా? → Tool save_lead(question=caller text, reason=unknown_amenity). Say: ఇప్పుడు confirm చేసి team చెబుతారు అండి.
2) Caller: RERA approval number ఏమిటి? → save_lead(reason=missing_fact). Say: ఆ detail ఇప్పుడు note చేసి మా team share చేస్తారు.
3) Caller: MBA aviation course ఉందా? → save_lead. Say: course గురించి confirm చేసి call back చేస్తాం అండి.
4) Caller: spa and jacuzzi ఉన్నాయా? → save_lead. Say: amenities confirm అవ్వాలి — team త్వరలో చెబుతారు.
UNKNOWN FACT RULE: If the exact fact is not in FACTS below, you MUST call save_lead in the same turn.
Never invent negatives (e.g. "X లేదు / we don't have X") unless FACTS explicitly says so — say confirm చేసి చెప్తాము and save_lead."""
    extras = [
        f"CALENDAR (Asia/Kolkata, authoritative for dates):\n{cal}",
        f"LANGUAGE RULES: {lang_rules}",
        f"OBJECTIONS:\n{_objection_block(p)}",
        "LENGTH: Exactly 1–2 short sentences, ~30 words total. Turn 1 identity question → name + one hook + one question only.",
        "TOOLS: use native function calls when needed (save_lead, check_availability, create_booking, "
        "transfer_to_human, send_whatsapp_details, end_call). Never print JSON or <tool_call> tags.",
        "BOOKING: Follow the BOOKING slot line each turn — fill one missing slot at a time. "
        "Never call create_booking until status=awaiting_confirm and caller says yes.",
        "DATES: Speak check-in/check-out ONLY from call_state ISO dates in the calendar. "
        "Never invent check-out — if missing, ask how many nights (ఎన్ని nights అండి?).",
        "AVAILABILITY: Never say rooms available/vacant unless a tool confirmed it this call. "
        "After check_availability, say team will confirm by phone.",
        few_shot.strip(),
    ]
    repeat = _no_repeat_hint(last_agent_replies or [])
    if repeat:
        extras.append(repeat)
    return f"{body}\n\n" + "\n\n".join(extras)


def render_prompt_for_report(
    *,
    persona_name: str,
    business_name: str,
    facts: str,
    vertical: str = "lodging",
    profile: dict | None = None,
) -> str:
    return build_voice_system_prompt(
        persona_name=persona_name,
        business_name=business_name,
        facts=facts,
        reply_language="te-IN",
        vertical=vertical,
        profile=profile,
        last_agent_replies=[],
    )