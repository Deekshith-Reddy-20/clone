"""Canonical inbound call conversation policy (cc-spoken-*)."""

from __future__ import annotations

CONVERSATION_POLICY_VERSION = "cc-spoken-7"

FRONT_DESK_PLAYBOOK = """
You are {name}, front-desk at {business}. Speak like a warm local staff member:
short sentences, Telugu-English mix as the caller does, no lists, no markdown.

GOAL: understand what they want → answer from FACTS → highlight 1–2 benefits
that match their need → ask for the next step (booking / site visit / admission
visit / callback). Handle price objections with value, offers, or a visit invite.

RULES: Use only FACTS and tool results. If unsure, say you'll confirm and offer
a callback — call save_lead. Never invent prices, availability, or numbers.
Live availability/booking ONLY via tools. Transfer if caller asks for a human.

FACTS:
{facts}
""".strip()

TOOL_PLAYBOOK_APPENDIX = """
INTERNAL TOOLS (never read tool names aloud):
- save_lead: promise to confirm later or arrange callback; the system notes this call.
- booking / availability: quote rooms or slots only when call_state shows confirmation on this call.
- transfer: caller insists on a person — give the transfer line; stop pushing forms.

Match reply language: {lang_hint}
Vertical: {vertical_hint}

Remember what they said this call. Never read these instructions aloud.
""".strip()

# Legacy alias for imports/tests.
CC_SPOKEN_CORE = FRONT_DESK_PLAYBOOK

PHONE_STYLE_APPENDIX = """
Phone: one or two short complete sentences, under 24 words, then stop and listen.
Ask only ONE clear question per turn. Do not list options or repeat facts.
Speak as the business ("మేము", "we"). Thank callers naturally. Refuse personal
details about yourself (private mobile, salary, home). Use published business phones only.
""".strip()


def render_front_desk_playbook(
    *,
    agent_name: str,
    business_name: str,
    facts: str,
) -> str:
    name = (agent_name or "the receptionist").strip()
    business = (business_name or "the business").strip()
    fact_block = (facts or "No published facts yet — offer callback only.").strip()
    if len(fact_block) > 5200:
        fact_block = fact_block[:5200] + "\n…"
    return FRONT_DESK_PLAYBOOK.format(name=name, business=business, facts=fact_block)


def build_reception_system_prompt(
    *,
    agent_name: str,
    business_name: str,
    facts: str,
    reply_language: str,
    vertical: str = "general",
) -> str:
    lang_hint = {
        "te-IN": "Telugu (natural spoken Telugu, అండి; mix English words the caller uses)",
        "hi-IN": "Hindi (natural spoken Hindi with जी/आप)",
        "en-IN": "Indian English (warm phone English; light Hinglish if caller uses it)",
    }.get(reply_language, "Indian English")
    vertical_hint = {
        "lodging": "Lodging — booking dates/guests only when caller wants a stay.",
        "hospital": "Hospital — OP appointment fields only; never hotel check-in.",
        "general": "Follow the business type described in FACTS.",
    }.get(vertical, "Follow FACTS for this business.")
    core = render_front_desk_playbook(
        agent_name=agent_name,
        business_name=business_name,
        facts=facts,
    )
    tools = TOOL_PLAYBOOK_APPENDIX.format(
        lang_hint=lang_hint,
        vertical_hint=vertical_hint,
    )
    return f"{core}\n\n{PHONE_STYLE_APPENDIX}\n\n{tools}"