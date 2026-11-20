"""Render BusinessProfile into a speakable FACTS block for the LLM."""

from __future__ import annotations

from app.schemas.business_profile import BusinessProfile


def render_profile_facts(profile: BusinessProfile) -> str:
    """Telugu-friendly key lines; no instructions."""
    p = profile
    lines: list[str] = []
    if p.business.name:
        lines.append(f"Business: {p.business.name}")
    if p.business.one_line_pitch:
        lines.append(f"About: {p.business.one_line_pitch}")
    loc = p.location
    if loc.full_address:
        lines.append(f"Address: {loc.full_address}")
    if loc.area:
        lines.append(f"Area: {loc.area}")
    if loc.city:
        lines.append(f"City: {loc.city}")
    if loc.state:
        lines.append(f"State: {loc.state}")
    for lm in loc.landmarks[:6]:
        lines.append(f"Landmark: {lm}")
    for d in loc.directions[:6]:
        lines.append(f"Directions: {d}")
    for d in loc.distance_from[:4]:
        bit = f"{d.place}"
        if d.km is not None:
            bit += f" {d.km} km"
        if d.drive_time:
            bit += f" ({d.drive_time})"
        lines.append(f"Distance: {bit}")
    c = p.contact
    if c.reception_phone:
        lines.append(f"Reception phone: {c.reception_phone}")
    if c.hours:
        lines.append(f"Hours: {c.hours}")
    for off in p.offerings[:12]:
        price = ""
        if off.price_from is not None:
            price = f" from Rs {off.price_from:g}"
            if off.price_unit:
                price += f" {off.price_unit}"
        lines.append(f"Offering {off.name}: {off.description}{price}. {off.price_notes}".strip())
    for u in p.usps[:8]:
        lines.append(f"USP: {u}")
    for o in p.offers[:6]:
        lines.append(f"Offer: {o.text}")
    pol = p.policies
    if pol.check_in:
        lines.append(f"Check-in: {pol.check_in}")
    if pol.check_out:
        lines.append(f"Check-out: {pol.check_out}")
    for faq in p.faqs[:15]:
        lines.append(f"FAQ Q: {faq.q}")
        lines.append(f"FAQ A: {faq.a}")
    for am in p.amenities[:15]:
        lines.append(f"Amenity: {am}")
    return "\n".join(lines).strip()