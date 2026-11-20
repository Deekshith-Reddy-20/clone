"""Callback / lead intent during live calls (save_lead tool semantics)."""

from __future__ import annotations

import re
from datetime import UTC, datetime


def is_human_transfer_request(text: str) -> bool:
    te = (text or "").strip()
    low = te.lower()
    return bool(
        re.search(
            r"(talk to|speak to|connect).{0,20}(human|person|agent|manager|owner|staff)",
            low,
            re.I,
        )
        or re.search(r"(real person|live agent|కాన్సెల్|మనిషి|అసలైన|మనుష్యుడు|व्यक्ति|इंसान)", te + low, re.I)
        or any(p in low for p in ("transfer me", "human please", "agent please"))
        or "మనిషి" in te
        or "హ్యూమన్" in te
    )


def transfer_reply(lang: str) -> str:
    if lang == "te-IN":
        return "సరే అండి, మీకు మన staff కి కనెక్ట్ చేస్తాను — ఒక్క నిమిషం లైన్‌లో ఉండండి."
    if lang == "hi-IN":
        return "ठीक है जी, मैं आपको हमारी टीम से जोड़ती हूँ — एक मिनट लाइन पर रहिए।"
    return "Sure — I'll connect you with our team. Please stay on the line."


def is_price_objection(text: str) -> bool:
    te = text or ""
    low = te.lower()
    return bool(
        re.search(
            r"(too (much|high|costly)|expensive|overpriced|can't afford|cheaper|discount|"
            r"ఎక్కువ|ఖరీదు|డిస్కౌంట్|ఆఫర్|कीमत|महंगा|सस्ता)",
            low + te,
            re.I,
        )
    )


def try_value_offer_snippet(
    caller_text: str,
    *,
    website_knowledge: str | None,
    brief: str,
    lang: str,
) -> str | None:
    if not is_price_objection(caller_text):
        return None
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
    if not corpus.strip():
        return None
    low_corpus = corpus.lower()
    for line in re.split(r"[\n.]+", corpus):
        ll = line.lower()
        if any(
            k in ll
            for k in (
                "offer",
                "discount",
                "package",
                "value",
                "complimentary",
                "free",
                "weekend",
                "ఆఫర్",
                "డిస్కౌంట్",
                "ಪ್ಯಾಕేజ్",
                "ऑफर",
            )
        ):
            fact = line.strip()[:140]
            if lang == "te-IN":
                return f"అర్థమైంది అండి. మీకు ఇది సూట్ అవుతుంది: {fact} సైట్ విజిట్ లేదా బుకింగ్ చూద్దామా?"
            return f"I hear you. From our published offers: {fact} Shall we book or plan a visit?"
    if any(k in low_corpus for k in ("offer", "discount", "package", "ఆఫర్")):
        return None
    if lang == "te-IN":
        return "ఖర్చు గురించి అర్థమైంది అండి. ఖచ్చితమైన రేట్ సైట్/PDF లో ఉన్నదే చెప్తాను; సూట్ అయితే విజిట్ లేదా బుకింగ్ చూద్దామా?"
    return "I understand on price. I'll only quote rates from our published facts. Want to visit or book?"


def is_callback_confirm_offer(text: str) -> bool:
    te = (text or "").strip()
    low = te.lower()
    return bool(
        re.search(r"(call (me )?back|callback|confirm later|get back|తిరిగి కాల్)", low + te, re.I)
        or "కాల్ బ్యాక్" in te
    )


def callback_promise_reply(lang: str) -> str:
    if lang == "te-IN":
        return "సరే అండి, నోట్ చేసుకున్నాను — మన టీమ్ మీకు తిరిగి కాల్ చేస్తారు."
    if lang == "hi-IN":
        return "ठीक है जी, नोट कर लिया — हमारी टीम आपको वापस कॉल करेगी।"
    return "Noted — our team will call you back."


def save_lead_intent(fields: dict, *, reason: str, caller_text: str = "") -> dict:
    """Record save_lead semantics on the call (no separate tool invocation)."""
    note = {
        "reason": (reason or "callback")[:200],
        "snippet": (caller_text or "")[:300],
        "at": datetime.now(UTC).isoformat(),
    }
    pending = list(fields.get("voice_lead_intents") or [])
    pending.append(note)
    fields["voice_lead_intents"] = pending[-8:]
    fields["voice_callback_requested"] = True
    return fields