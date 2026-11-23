#!/usr/bin/env python3
"""Idempotent staging seed: V-Farms Reservations AI Employee (draft / not live traffic).

Does not overwrite Harish Outpero script. Does not place calls.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Employee, EmployeeDraft  # noqa: E402
from app.models.enums import CallMode, EmployeeStatus  # noqa: E402
from app.models.outpero import OutperoAgent  # noqa: E402
from app.services.outpero.agents import ensure_env_agent  # noqa: E402

WORKSPACE_ID = uuid.UUID("b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3")
MARKER = "vfarms_reservations_staging_v1"
SOURCE_URL = "https://vfarms.in/"
FETCHED_AT = datetime.now(UTC).isoformat()

KNOWLEDGE = f"""
# V-Farms Reservations — verified knowledge snapshot
source: {SOURCE_URL}
fetched_at: {FETCHED_AT}
marker: {MARKER}

## Property (one bookable estate)
- Name: V-Farms — private farm stay / whole-estate booking
- Location: Parikibanda, Manoharabad Mandal, Medak, Telangana 502336
- Drive: about 45–60 minutes from Hyderabad via Medchal / Manoharabad
- Estate: five acres with dragon fruit plantation; booking is for the entire property
- Rooms/spaces (all included in one whole-resort booking): The Canopy, The Orchard, The Courtyard, The Veranda, The Studio
- Contact: WhatsApp/phone +91 99086 27778; email hello@vfarms.in
- Official checkout / calendar: {SOURCE_URL}#book

## Published stay times (FAQ)
- Check-in from 12:00 noon
- Check-out by 10:30 AM
- Host may arrange different times in advance

## Published guest / rate bands (site copy — live quote is authoritative)
- Guests: 1–50
- Up to 20 guests: ₹25,000 / night
- 21–50 guests: ₹30,000 / night
- Tax appears on the live quote; always use check_stay_availability for total

## FAQ (verified from site)
- Included: entire property — all five rooms, shared indoor spaces, lawns, pool access, farm setting. Meals/extra services confirmed when booking.
- Children welcome. Pets case-by-case — ask guest to WhatsApp before booking.
- Private parking on the estate for vehicles arriving with the party.
- Cancellation: contact V-Farms with booking reference; handled personally.
- Do not invent unpublished rates, blocked dates, or policies.

## Short phone-ready FAQs
Q: Does one booking include the whole property and all the rooms?
A: Yes. A stay reserves the entire estate and all five rooms — The Canopy, The Orchard, The Courtyard, The Veranda, and The Studio.

Q: What time are check-in and checkout?
A: Check-in is from 12:00 noon, and checkout is by 10:30 AM, unless arranged with the host in advance.

Q: How many guests can stay, and what are published rates?
A: Published range is 1–50 guests. Site bands are ₹25,000/night up to 20 guests and ₹30,000/night for 21–50. Live quote including tax is authoritative — never invent a total.

Q: Is this date available / what is the price?
A: I will check the live booking system. I will not guess availability or the total.

## Agent rules for voice
- Knowledge answers FAQs only.
- Live availability and price come ONLY from Karyuk action check_stay_availability → V-Farms APIs.
- Staging quote-only route: use check_stay_availability and create_staff_followup. Do not call create_stay_reservation until an authorized booking sandbox is connected and writes are approved.
- Website write sequence (when authorized): hold then confirm. No online payment step.
- Never say "Your stay is confirmed" unless create_stay_reservation returns state=confirmed with a V-Farms reservation reference. Quote, hold, writes_blocked, or unknown are not confirmation.
- Never collect card numbers, OTPs, or UPI PINs. There is no online payment step on the active website path.
- Mark lead Won only from verified booking state, never from a completed call alone.
""".strip()

BRIEF = (
    "You are the V-Farms Reservations assistant for the Parikibanda estate. "
    "Answer property FAQs from knowledge. For stays: collect check-in, checkout, and guest count; "
    "read dates back in Asia/Kolkata; call check_stay_availability; read the live total; "
    "on this quote-only staging path offer staff follow-up via create_staff_followup for booking "
    "requests instead of submitting a live hold. One whole estate per booking. Never invent rates "
    "or say the stay is confirmed without a confirmed V-Farms reservation reference."
)

OPERATOR = (
    "STAGING QUOTE-ONLY. Do not overwrite live Harish script. "
    "Outpero Custom API for this route: check_stay_availability + create_staff_followup only. "
    "Do not attach create_stay_reservation until an authorized sandbox and writes approval exist. "
    "Action auth: X-Outpero-Action-Secret (not post-call signing secret). "
    f"Knowledge marker {MARKER}."
)


def main() -> int:
    db = SessionLocal()
    try:
        ensure_env_agent(db)
        agent = db.execute(
            select(OutperoAgent).where(OutperoAgent.workspace_id == WORKSPACE_ID)
        ).scalars().first()
        if agent and not agent.action_secret:
            import secrets

            agent.action_secret = secrets.token_urlsafe(24)
            db.commit()
            print("action_secret_ensured=1")
        else:
            print("action_secret_ensured=0")

        existing_draft = None
        for draft in db.execute(
            select(EmployeeDraft).where(EmployeeDraft.workspace_id == WORKSPACE_ID)
        ).scalars():
            if MARKER in (draft.website_knowledge or "") or MARKER in (draft.operator_instructions or ""):
                existing_draft = draft
                break

        if existing_draft:
            employee = db.get(Employee, existing_draft.employee_id)
            existing_draft.brief = BRIEF
            existing_draft.website_url = SOURCE_URL
            existing_draft.website_knowledge = KNOWLEDGE
            existing_draft.operator_instructions = OPERATOR
            existing_draft.language = "English"
            existing_draft.mode = CallMode.instant
            existing_draft.business_profile = {
                "business": {"name": "V-Farms", "type": "estate_stay"},
                "location": {
                    "full_address": "Parikibanda, Manoharabad Mandal, Medak, Telangana 502336",
                    "area": "Parikibanda",
                    "city": "Manoharabad",
                    "state": "Telangana",
                },
                "contact": {
                    "reception_phone": "+919908627778",
                    "whatsapp": "+919908627778",
                    "email": "hello@vfarms.in",
                },
                "policies": {"check_in": "12:00 noon", "check_out": "10:30 AM"},
                "sources": [{"url": SOURCE_URL, "fetched_at": FETCHED_AT, "marker": MARKER}],
            }
            existing_draft.revision += 1
            if employee and employee.status == EmployeeStatus.published:
                # Keep staged: do not leave published for live DID until review
                employee.status = EmployeeStatus.draft
            db.commit()
            print(json.dumps({
                "status": "updated",
                "employee_id": str(existing_draft.employee_id),
                "draft_revision": existing_draft.revision,
                "employee_status": employee.status if employee else None,
                "published_version": None,
                "outpero_agent_slug": agent.slug if agent else None,
                "knowledge_marker": MARKER,
                "source": SOURCE_URL,
                "fetched_at": FETCHED_AT,
            }))
            return 0

        employee = Employee(workspace_id=WORKSPACE_ID, status=EmployeeStatus.draft)
        db.add(employee)
        db.flush()
        draft = EmployeeDraft(
            employee_id=employee.id,
            workspace_id=WORKSPACE_ID,
            brief=BRIEF,
            language="English",
            natural_spoken=True,
            mode=CallMode.instant,
            website_url=SOURCE_URL,
            website_knowledge=KNOWLEDGE,
            operator_instructions=OPERATOR,
            tts_speaker="shubh",
            business_profile={
                "business": {"name": "V-Farms", "type": "estate_stay"},
                "location": {
                    "full_address": "Parikibanda, Manoharabad Mandal, Medak, Telangana 502336",
                    "area": "Parikibanda",
                    "city": "Manoharabad",
                    "state": "Telangana",
                },
                "contact": {
                    "reception_phone": "+919908627778",
                    "whatsapp": "+919908627778",
                    "email": "hello@vfarms.in",
                },
                "policies": {"check_in": "12:00 noon", "check_out": "10:30 AM"},
                "sources": [{"url": SOURCE_URL, "fetched_at": FETCHED_AT, "marker": MARKER}],
            },
        )
        db.add(draft)
        db.commit()
        print(json.dumps({
            "status": "created",
            "employee_id": str(employee.id),
            "draft_revision": draft.revision,
            "employee_status": employee.status,
            "published_version": None,
            "outpero_agent_slug": agent.slug if agent else None,
            "knowledge_marker": MARKER,
            "source": SOURCE_URL,
            "fetched_at": FETCHED_AT,
        }))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
