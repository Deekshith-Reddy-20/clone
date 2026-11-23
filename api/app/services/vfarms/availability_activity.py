"""Record + serialize V-Farms availability-check lifecycle (no secrets / phones)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.vfarms import VfarmsAvailabilityActivity


def begin_availability_activity(
    db: Session,
    *,
    workspace_id: UUID,
    provider_call_id: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
    guest_count: int | None = None,
) -> VfarmsAvailabilityActivity:
    sid = (provider_call_id or "").strip() or None
    row = VfarmsAvailabilityActivity(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        state="checking",
        correlation="independent",
        provider_call_id=sid,
        check_in=check_in,
        check_out=check_out,
        guest_count=guest_count,
        started_at=datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def complete_availability_activity(
    db: Session,
    row: VfarmsAvailabilityActivity,
    *,
    state: str,
    correlation: str = "independent",
    associated_call_id: UUID | None = None,
    quote_ref: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
    guest_count: int | None = None,
    total_inr: int | None = None,
    currency: str | None = None,
    error_code: str | None = None,
) -> VfarmsAvailabilityActivity:
    row.state = state
    row.correlation = correlation
    row.associated_call_id = associated_call_id
    if quote_ref is not None:
        row.quote_ref = quote_ref
    if check_in is not None:
        row.check_in = check_in
    if check_out is not None:
        row.check_out = check_out
    if guest_count is not None:
        row.guest_count = guest_count
    if total_inr is not None:
        row.total_inr = total_inr
    if currency is not None:
        row.currency = currency
    if error_code is not None:
        row.error_code = error_code
    row.completed_at = datetime.now(UTC)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def serialize_availability_activity(row: VfarmsAvailabilityActivity) -> dict[str, Any]:
    label = {
        "checking": "Checking availability",
        "quote_ready": "Quote ready",
        "unavailable": "Unavailable",
        "lookup_failed": "Lookup failed",
    }.get(row.state, row.state)
    correlation_note = None
    if row.correlation == "independent":
        correlation_note = (
            "Independent quote activity — no verified provider call ID link."
            if not row.provider_call_id
            else "Provider call ID was supplied but this row is not linked to a workspace call."
        )
    elif row.correlation == "linked":
        correlation_note = "Linked via verified provider_call_id / call_id."
    elif row.correlation == "link_attempted_not_found":
        correlation_note = (
            "Provider call ID was supplied but no matching call exists in this workspace yet."
        )

    return {
        "id": str(row.id),
        "kind": "availability_activity",
        "state": row.state,
        "label": label,
        "correlation": row.correlation,
        "correlation_note": correlation_note,
        "provider_call_id": row.provider_call_id,
        "associated_call_id": str(row.associated_call_id) if row.associated_call_id else None,
        "quote_ref": row.quote_ref,
        "check_in": row.check_in,
        "check_out": row.check_out,
        "guest_count": row.guest_count,
        "total": row.total_inr,
        "currency": row.currency,
        "error_code": row.error_code,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "is_reservation": False,
        "in_flight": row.state == "checking" and row.completed_at is None,
    }


# Identifiable isolated QA correlation tokens. Ordinary operator feeds exclude these
# so intentional test writes never appear as customer activity.
_QA_PROVIDER_CALL_PREFIXES = ("qa-live-inbound-", "qa-")


def is_isolated_qa_activity(row: VfarmsAvailabilityActivity) -> bool:
    sid = (row.provider_call_id or "").strip().lower()
    if not sid:
        return False
    return any(sid.startswith(prefix) for prefix in _QA_PROVIDER_CALL_PREFIXES)


def list_availability_activity(
    db: Session,
    *,
    workspace_id: UUID,
    limit: int = 50,
    include_isolated_qa: bool = False,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    # Over-fetch slightly when filtering QA so ordinary feed still fills the limit.
    fetch_limit = limit if include_isolated_qa else min(100, max(limit * 2, limit + 10))
    rows = db.scalars(
        select(VfarmsAvailabilityActivity)
        .where(VfarmsAvailabilityActivity.workspace_id == workspace_id)
        .order_by(desc(VfarmsAvailabilityActivity.started_at))
        .limit(fetch_limit)
    ).all()
    if not include_isolated_qa:
        rows = [row for row in rows if not is_isolated_qa_activity(row)]
    return [serialize_availability_activity(row) for row in rows[:limit]]


def get_availability_activity(
    db: Session,
    *,
    workspace_id: UUID,
    activity_id: UUID,
    include_isolated_qa: bool = False,
) -> dict[str, Any] | None:
    row = db.get(VfarmsAvailabilityActivity, activity_id)
    if not row or row.workspace_id != workspace_id:
        return None
    if not include_isolated_qa and is_isolated_qa_activity(row):
        return None
    return serialize_availability_activity(row)
