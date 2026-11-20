"""When location detail is exhausted, offer WhatsApp + save_lead."""

from __future__ import annotations

import re

from app.schemas.business_profile import BusinessProfile


_LOCATION_Q = re.compile(
    r"(location|direction|address|landmark|map|ఎక్కడ|లోకేషన్|దిశ|చిరునామా|land\s*mark)",
    re.I,
)


def is_location_followup(caller_text: str) -> bool:
    return bool(_LOCATION_Q.search(caller_text or ""))


_WHATSAPP_OFFER = re.compile(
    r"(whatsapp|whats\s*app).{0,100}(పంప|send|share|ఇవ్వ|కావా|want|మీకు)",
    re.I,
)
_WHATSAPP_OFFER_Q = re.compile(
    r"(whatsapp.{0,40}\?|పంపమా|send.{0,25}whatsapp|share.{0,25}whatsapp)",
    re.I,
)
_WHATSAPP_ACCEPT = re.compile(
    r"(అవును|అవున|ఓకే|ok\b|okay|yes|yeah|sure|పంపండి|ఇవ్వండి|share\s+it|send\s+it)",
    re.I,
)


def agent_offered_whatsapp(agent_text: str) -> bool:
    t = agent_text or ""
    return bool(_WHATSAPP_OFFER.search(t) or _WHATSAPP_OFFER_Q.search(t))


def caller_accepted_whatsapp_offer(caller_text: str) -> bool:
    t = (caller_text or "").strip()
    if _WHATSAPP_ACCEPT.search(t):
        return True
    return bool(re.search(r"(పంప|send).{0,15}(whatsapp|వాట్స్)", t, re.I))


def whatsapp_send_consented(caller_text: str, *, last_agent_reply: str) -> bool:
    """send_whatsapp_details only after explicit WhatsApp offer + caller yes."""
    if not agent_offered_whatsapp(last_agent_reply):
        return False
    return caller_accepted_whatsapp_offer(caller_text)


def location_detail_remaining(profile: BusinessProfile, already_spoken: str) -> bool:
    low = (already_spoken or "").lower()
    loc = profile.location
    for lm in loc.landmarks:
        if lm and lm.lower() not in low:
            return True
    for d in loc.directions:
        if d and d.lower() not in low:
            return True
    if loc.maps_link and "map" not in low:
        return True
    for df in loc.distance_from:
        bit = f"{df.place}".lower()
        if bit and bit not in low:
            return True
    return False