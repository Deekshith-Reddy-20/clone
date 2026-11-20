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