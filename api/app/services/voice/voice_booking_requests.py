"""Persist voice booking requests (pending_staff)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Call, VoiceBookingRequest

logger = logging.getLogger(__name__)


def create_voice_booking_request(
    db: Session,
    call: Call,
    *,
    details: dict,
    note: str | None = None,
) -> VoiceBookingRequest:
    row = VoiceBookingRequest(
        workspace_id=call.workspace_id,
        call_id=call.id,
        employee_id=call.employee_id,
        status="pending_staff",
        caller_phone=str((call.captured_fields or {}).get("caller_e164") or "")[:32] or None,
        details=details,
        note=(note or "")[:2000] or None,
        notify_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("voice_booking_request id=%s call=%s", row.id, call.id)
    from app.services.owner_notify import load_workspace_owner, notify_owner

    wo, contacts = load_workspace_owner(db, call.workspace_id)
    subj = f"Voice booking request ({row.id})"
    body = f"Call {call.id}\nPhone {row.caller_phone}\nDetails: {details}"
    status, ch = notify_owner(
        subject=subj, body=body, workspace_owner=wo, contacts=contacts
    )
    row.notify_status = status if status != "skipped" else "skipped_no_channel"
    det = dict(details)
    det["owner_notify_channel"] = ch
    row.details = det
    db.commit()
    fields = dict(call.captured_fields or {})
    fields["booking_request_id"] = str(row.id)
    call.captured_fields = fields
    db.commit()
    return row

