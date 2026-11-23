"""Scoped V-Farms stay actions for Outpero mid-call Custom API.

Website contract (vfarms.in, verified from booking frontend):
  quote → guest name/email/phone → POST /api/bookings/hold → POST /api/bookings/confirm
  Confirmed only when confirm returns status == "confirmed" and a booking_reference exists.
  No online payment step; site copy says payment checkout is paused / confirm without payment.
  Hold alone is not a confirmation.

States returned to the agent (spoken carefully):
  unavailable | quote_ready | quote_changed | quote_expired |
  missing_guest_fields | confirmed | unknown | declined | writes_blocked |
  followup_saved
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Call, VoiceBookingRequest
from app.models.vfarms import VfarmsBookingAttempt, VfarmsStayQuote
from app.services.vfarms import client as vfarms_client
from app.services.vfarms.availability_activity import (
    begin_availability_activity,
    complete_availability_activity,
)
from app.services.vfarms.client import VfarmsApiError

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
PROPERTY = "vfarms_estate"


def _parse_ymd(value: Any) -> date | None:
    if value is None:
        return None
    raw = str(value).strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _spoken_safe(d: date) -> str:
    # Portable (no %-d on Windows); Linux accepts %#d / %-d — use day without leading zero manually.
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def validate_stay_inputs(
    *,
    check_in: Any,
    check_out: Any,
    guest_count: Any,
) -> tuple[date, date, int] | dict[str, Any]:
    cin = _parse_ymd(check_in)
    cout = _parse_ymd(check_out)
    try:
        guests = int(guest_count)
    except (TypeError, ValueError):
        guests = -1
    if cin is None or cout is None:
        return {
            "state": "unknown",
            "speak": "I need exact check-in and checkout dates. Please say the calendar dates again.",
            "error": "ambiguous_dates",
        }
    if guests < 1 or guests > 50:
        return {
            "state": "unknown",
            "speak": "Guest count must be between 1 and 50 for a whole-estate stay.",
            "error": "invalid_guest_count",
        }
    if cout <= cin:
        return {
            "state": "unknown",
            "speak": "Checkout must be after check-in. Please confirm both dates.",
            "error": "invalid_date_order",
        }
    today = datetime.now(IST).date()
    if cin < today:
        return {
            "state": "unavailable",
            "speak": "Those check-in dates are in the past. Please choose a future stay.",
            "error": "past_check_in",
        }
    return cin, cout, guests


def _resolve_associated_call(
    db: Session,
    *,
    workspace_id: UUID,
    call_id: Any = None,
    provider_call_id: Any = None,
) -> Call | None:
    """Locate a workspace Outpero call by karyuk id or provider call id. No summary inference."""
    if call_id:
        try:
            cid = UUID(str(call_id).strip())
        except ValueError:
            cid = None
        if cid is not None:
            row = db.get(Call, cid)
            if row and row.workspace_id == workspace_id and row.provider == "outpero":
                return row
    sid = str(provider_call_id or "").strip()
    if not sid:
        return None
    return db.scalars(
        select(Call).where(
            Call.workspace_id == workspace_id,
            Call.provider == "outpero",
            Call.provider_call_sid == sid,
        )
    ).first()


def _attach_quote_evidence(
    db: Session,
    *,
    call: Call,
    quote_payload: dict[str, Any],
    association: str,
) -> None:
    fields = dict(call.captured_fields or {})
    fields["quote_evidence"] = {
        "quote_ref": quote_payload.get("quote_ref"),
        "state": quote_payload.get("state"),
        "check_in": quote_payload.get("check_in"),
        "check_out": quote_payload.get("check_out"),
        "guest_count": quote_payload.get("guest_count"),
        "nights": quote_payload.get("nights"),
        "total": quote_payload.get("total"),
        "currency": quote_payload.get("currency"),
        "rate_per_night": quote_payload.get("rate_per_night"),
        "associated_at": datetime.now(UTC).isoformat(),
        "association": association,
    }
    call.captured_fields = fields
    db.add(call)
    db.commit()


def _activity_correlation(
    *,
    associated_call: Call | None,
    call_id: Any,
    provider_call_id: Any,
) -> str:
    if associated_call is not None:
        return "linked"
    if call_id or provider_call_id:
        return "link_attempted_not_found"
    return "independent"


def check_stay_availability(
    db: Session,
    *,
    workspace_id: UUID,
    check_in: Any,
    check_out: Any,
    guest_count: Any,
    call_id: Any = None,
    provider_call_id: Any = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.vfarms_actions_enabled:
        return {"state": "unknown", "speak": "Stay availability checks are temporarily unavailable.", "error": "disabled"}

    validated = validate_stay_inputs(check_in=check_in, check_out=check_out, guest_count=guest_count)
    if isinstance(validated, dict):
        # Invalid inputs never enter a durable "checking" row — nothing was in flight.
        return validated
    cin, cout, guests = validated
    associated_call = _resolve_associated_call(
        db,
        workspace_id=workspace_id,
        call_id=call_id,
        provider_call_id=provider_call_id,
    )
    association = (
        "provider_call_id"
        if provider_call_id and associated_call and str(provider_call_id).strip() == (associated_call.provider_call_sid or "")
        else "call_id"
        if associated_call
        else None
    )
    correlation = _activity_correlation(
        associated_call=associated_call,
        call_id=call_id,
        provider_call_id=provider_call_id,
    )
    activity = begin_availability_activity(
        db,
        workspace_id=workspace_id,
        provider_call_id=str(provider_call_id).strip() if provider_call_id else None,
        check_in=cin.isoformat(),
        check_out=cout.isoformat(),
        guest_count=guests,
    )

    def _finish(
        *,
        state: str,
        result: dict[str, Any],
        quote_ref: str | None = None,
        total_inr: int | None = None,
        currency: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        complete_availability_activity(
            db,
            activity,
            state=state,
            correlation=correlation,
            associated_call_id=associated_call.id if associated_call else None,
            quote_ref=quote_ref,
            check_in=cin.isoformat(),
            check_out=cout.isoformat(),
            guest_count=guests,
            total_inr=total_inr,
            currency=currency,
            error_code=error_code,
        )
        result = {
            **result,
            "availability_activity_id": str(activity.id),
            "availability_correlation": correlation,
        }
        return result

    # Read live calendar first so we can say unavailable without inventing rates.
    try:
        cal = vfarms_client.fetch_calendar(date_from=cin.isoformat(), date_to=cout.isoformat())
    except VfarmsApiError as exc:
        logger.warning("vfarms_calendar_error %s", exc)
        return _finish(
            state="lookup_failed",
            error_code="calendar_error",
            result={
                "state": "unknown",
                "speak": "I could not verify live availability just now. I can note a staff follow-up.",
                "error": "calendar_error",
            },
        )

    blocked = set(cal.get("blockedNights") or [])
    nights = []
    cur = cin
    while cur < cout:
        nights.append(cur.isoformat())
        cur += timedelta(days=1)
    if any(n in blocked for n in nights):
        return _finish(
            state="unavailable",
            result={
                "state": "unavailable",
                "speak": (
                    f"The estate is not available from {_spoken_safe(cin)} to {_spoken_safe(cout)} "
                    f"Asia/Kolkata. I can check other dates or create a staff follow-up."
                ),
                "check_in": cin.isoformat(),
                "check_out": cout.isoformat(),
                "guest_count": guests,
                "timezone": "Asia/Kolkata",
                "property": PROPERTY,
            },
        )

    try:
        raw = vfarms_client.fetch_quote(
            check_in=cin.isoformat(), check_out=cout.isoformat(), adults=guests
        )
    except VfarmsApiError as exc:
        msg = str(exc)
        if "not available" in msg.lower() or "invalid" in msg.lower():
            return _finish(
                state="unavailable",
                error_code="quote_unavailable",
                result={
                    "state": "unavailable",
                    "speak": (
                        f"Those dates are not available for {_spoken_safe(cin)} to {_spoken_safe(cout)}. "
                        "Shall I check different dates?"
                    ),
                    "error": msg,
                },
            )
        return _finish(
            state="lookup_failed",
            error_code="quote_error",
            result={
                "state": "unknown",
                "speak": "I could not get a live price just now. I can create a staff follow-up instead.",
                "error": msg,
            },
        )

    if not raw.get("available"):
        return _finish(
            state="unavailable",
            result={
                "state": "unavailable",
                "speak": f"The estate is not available from {_spoken_safe(cin)} to {_spoken_safe(cout)}.",
                "check_in": cin.isoformat(),
                "check_out": cout.isoformat(),
                "guest_count": guests,
            },
        )

    q = raw.get("quote") or {}
    total = int(q.get("total") or 0)
    due = int(q.get("amountDueNow") or total)
    nights_n = int(q.get("nights") or len(nights))
    rate = int(q.get("ratePerNight") or 0)
    currency = str(q.get("currency") or "INR")
    quote_ref = f"vfq_{secrets.token_urlsafe(10)}"
    expires = datetime.now(UTC) + timedelta(seconds=max(60, settings.vfarms_quote_ttl_seconds))

    source_payload: dict[str, Any] = {"quote": q, "property": PROPERTY}
    if associated_call is not None:
        source_payload["associated_call_id"] = str(associated_call.id)
        if associated_call.provider_call_sid:
            source_payload["associated_provider_call_id"] = associated_call.provider_call_sid

    row = VfarmsStayQuote(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        quote_ref=quote_ref,
        check_in=cin.isoformat(),
        check_out=cout.isoformat(),
        guest_count=guests,
        currency=currency,
        total_inr=total,
        amount_due_now_inr=due,
        rate_per_night_inr=rate,
        nights=nights_n,
        status="active",
        source_payload=source_payload,
        expires_at=expires,
    )
    db.add(row)
    db.commit()

    result = {
        "state": "quote_ready",
        "speak": (
            f"For the whole V-Farms estate, check-in {_spoken_safe(cin)}, checkout {_spoken_safe(cout)}, "
            f"{guests} guests, Asia/Kolkata: {nights_n} nights, total {total} {currency}. "
            "This is a live quote only, not a reservation. "
            "If you want these exact dates, I will need your name, email, and phone, then your clear yes to book."
        ),
        "quote_ref": quote_ref,
        "check_in": cin.isoformat(),
        "check_out": cout.isoformat(),
        "check_in_spoken": _spoken_safe(cin),
        "check_out_spoken": _spoken_safe(cout),
        "guest_count": guests,
        "nights": nights_n,
        "total": total,
        "currency": currency,
        "rate_per_night": rate,
        "timezone": "Asia/Kolkata",
        "property": PROPERTY,
        "expires_at": expires.isoformat(),
        "availability_is_hold": False,
        "required_guest_fields": ["guest_name", "guest_email", "guest_phone"],
        # amountDueNow exists on the quote API but the website does not run a payment step.
        "amount_due_now_reported_by_api": due,
        "online_payment_required": False,
    }

    if associated_call is not None and association:
        _attach_quote_evidence(
            db,
            call=associated_call,
            quote_payload=result,
            association=association,
        )
        result["associated_call_id"] = str(associated_call.id)
        result["associated_provider_call_id"] = associated_call.provider_call_sid
        result["quote_associated"] = True
    elif call_id or provider_call_id:
        result["quote_associated"] = False
        result["association_error"] = "call_not_found_in_workspace"

    return _finish(
        state="quote_ready",
        quote_ref=quote_ref,
        total_inr=total,
        currency=currency,
        result=result,
    )


def create_stay_reservation(
    db: Session,
    *,
    workspace_id: UUID,
    quote_ref: str,
    guest_name: str | None = None,
    guest_email: str | None = None,
    guest_phone: str | None = None,
    attempt_key: str | None = None,
    caller_confirmed: bool = False,
) -> dict[str, Any]:
    """Mirror the website submit path: re-quote → hold → confirm.

    Never treat hold-only or HTTP 200 as confirmed. Never invent a payment step.
    """
    settings = get_settings()
    if not settings.vfarms_actions_enabled:
        return {"state": "unknown", "speak": "Booking actions are temporarily unavailable.", "error": "disabled"}

    if not caller_confirmed:
        return {
            "state": "declined",
            "speak": "I will not book until you clearly say yes to these exact dates and the total.",
            "error": "caller_not_confirmed",
        }

    ref = (quote_ref or "").strip()
    if not ref:
        return {"state": "unknown", "speak": "I need the quote reference from the availability check.", "error": "missing_quote"}

    key = (attempt_key or "").strip() or f"att_{secrets.token_urlsafe(12)}"
    existing = db.execute(
        select(VfarmsBookingAttempt).where(
            VfarmsBookingAttempt.workspace_id == workspace_id,
            VfarmsBookingAttempt.attempt_key == key,
        )
    ).scalar_one_or_none()

    # Idempotent return for finished attempts.
    if existing and existing.status in {"confirmed", "writes_blocked"}:
        return dict(existing.result_payload or {})

    # Reconcile: prior hold/unknown with a booking id — retry confirm only, never a second hold.
    if existing and existing.vfarms_booking_id and existing.status in {
        "unknown",
        "held_pending_confirm",
    }:
        return _reconcile_confirm(
            db,
            workspace_id=workspace_id,
            attempt=existing,
            quote_ref=ref,
        )

    quote = db.execute(
        select(VfarmsStayQuote).where(
            VfarmsStayQuote.workspace_id == workspace_id,
            VfarmsStayQuote.quote_ref == ref,
        )
    ).scalar_one_or_none()
    if quote is None:
        return {"state": "unknown", "speak": "That quote was not found. Let me check availability again.", "error": "quote_missing"}
    if quote.status != "active":
        return {"state": "quote_expired", "speak": "That quote is no longer active. I can check live availability again.", "error": "quote_inactive"}
    if quote.expires_at.replace(tzinfo=quote.expires_at.tzinfo or UTC) < datetime.now(UTC):
        quote.status = "expired"
        db.commit()
        return {"state": "quote_expired", "speak": "That quote expired. I can check live availability again.", "error": "quote_expired"}

    name = (guest_name or "").strip()
    email = (guest_email or "").strip()
    phone = (guest_phone or "").strip()
    missing = [k for k, v in (("guest_name", name), ("guest_email", email), ("guest_phone", phone)) if not v]
    if missing:
        return {
            "state": "missing_guest_fields",
            "speak": (
                "Before I can submit the reservation, I need the guest name, email, and phone "
                "exactly as the V-Farms website requires."
            ),
            "missing": missing,
            "confirmed": False,
        }

    # Recheck authoritative availability + price before any write (same as website re-quote).
    try:
        live = vfarms_client.fetch_quote(
            check_in=quote.check_in, check_out=quote.check_out, adults=quote.guest_count
        )
    except VfarmsApiError as exc:
        return {
            "state": "unknown",
            "speak": "I could not recheck live availability. I will create a staff follow-up instead of booking.",
            "error": str(exc),
            "confirmed": False,
        }

    if not live.get("available"):
        quote.status = "unavailable"
        db.commit()
        return {
            "state": "unavailable",
            "speak": "Those dates are no longer available. I will not create a reservation.",
            "error": "became_unavailable",
            "confirmed": False,
        }

    live_q = live.get("quote") or {}
    live_total = int(live_q.get("total") or 0)
    if live_total != quote.total_inr:
        quote.status = "price_changed"
        db.commit()
        return {
            "state": "quote_changed",
            "speak": (
                f"The live total is now {live_total} {quote.currency}, which differs from the earlier quote "
                f"of {quote.total_inr}. I will not book until you approve the new total."
            ),
            "previous_total": quote.total_inr,
            "new_total": live_total,
            "currency": quote.currency,
            "confirmed": False,
        }

    if not settings.vfarms_booking_writes_enabled:
        result = {
            "state": "writes_blocked",
            "speak": (
                f"I have your approved dates {_spoken_safe(date.fromisoformat(quote.check_in))} to "
                f"{_spoken_safe(date.fromisoformat(quote.check_out))} for {quote.guest_count} guests, "
                f"total {quote.total_inr} {quote.currency}, plus name, email, and phone. "
                "Live V-Farms reservation writes are not enabled on this staging path, so I will not submit "
                "a hold or confirmation and I will not say the stay is booked. "
                "I am saving a staff follow-up with these exact details."
            ),
            "quote_ref": quote.quote_ref,
            "attempt_key": key,
            "total": quote.total_inr,
            "currency": quote.currency,
            "confirmed": False,
            "online_payment_required": False,
        }
        _save_attempt(db, workspace_id, key, quote.quote_ref, "writes_blocked", result)
        create_staff_followup(
            db,
            workspace_id=workspace_id,
            reason="voice_booking_writes_blocked",
            details={
                "quote_ref": quote.quote_ref,
                "check_in": quote.check_in,
                "check_out": quote.check_out,
                "guest_count": quote.guest_count,
                "total_inr": quote.total_inr,
                "guest_name": name,
                "guest_email": email,
                "guest_phone": phone,
            },
            caller_phone=phone,
        )
        return result

    # Website path: hold, then confirm. Hold is required; hold alone is not booked.
    try:
        hold = vfarms_client.create_hold(
            check_in=quote.check_in,
            check_out=quote.check_out,
            adults=quote.guest_count,
            guest_name=name,
            guest_email=email,
            guest_phone=phone,
        )
    except VfarmsApiError as exc:
        result = {
            "state": "unknown",
            "speak": (
                "The booking system did not finish the hold step. "
                "I will not say the stay is booked. Staff will verify before any retry."
            ),
            "error": str(exc),
            "timed_out": bool(getattr(exc, "timed_out", False)),
            "may_have_succeeded": bool(getattr(exc, "may_have_succeeded", False)),
            "attempt_key": key,
            "confirmed": False,
        }
        _save_attempt(db, workspace_id, key, quote.quote_ref, "unknown", result)
        create_staff_followup(
            db,
            workspace_id=workspace_id,
            reason="hold_uncertain",
            details={"quote_ref": quote.quote_ref, "attempt_key": key, "error": str(exc)},
            caller_phone=phone,
        )
        return result

    booking = hold.get("booking") or {}
    booking_id = str(booking.get("id") or "").strip()
    reference = str(booking.get("booking_reference") or "").strip()
    held_total = int(booking.get("total_inr") or live_total)
    if not booking_id:
        result = {
            "state": "unknown",
            "speak": "The hold response had no booking id. I will not say the stay is booked.",
            "attempt_key": key,
            "confirmed": False,
        }
        _save_attempt(db, workspace_id, key, quote.quote_ref, "unknown", result)
        return result

    if held_total != quote.total_inr:
        result = {
            "state": "quote_changed",
            "speak": (
                f"The hold total is {held_total} {quote.currency}, different from the quote. "
                "I will not confirm yet."
            ),
            "new_total": held_total,
            "vfarms_booking_id": booking_id,
            "vfarms_reference": reference or None,
            "confirmed": False,
        }
        _save_attempt(db, workspace_id, key, quote.quote_ref, "quote_changed", result, booking_id, reference or None)
        return result

    # Persist hold id before confirm so timeouts can reconcile without a second hold.
    _save_attempt(
        db,
        workspace_id,
        key,
        quote.quote_ref,
        "held_pending_confirm",
        {
            "state": "unknown",
            "speak": "Hold created; confirmation not finished.",
            "vfarms_booking_id": booking_id,
            "vfarms_reference": reference or None,
            "confirmed": False,
            "attempt_key": key,
        },
        booking_id,
        reference or None,
    )

    return _finish_confirm(
        db,
        workspace_id=workspace_id,
        quote_ref=quote.quote_ref,
        attempt_key=key,
        booking_id=booking_id,
        reference=reference,
        quote=quote,
    )


def _finish_confirm(
    db: Session,
    *,
    workspace_id: UUID,
    quote_ref: str,
    attempt_key: str,
    booking_id: str,
    reference: str,
    quote: VfarmsStayQuote | None = None,
) -> dict[str, Any]:
    try:
        confirmed = vfarms_client.confirm_booking(booking_id=booking_id)
    except VfarmsApiError as exc:
        result = {
            "state": "unknown",
            "speak": (
                "A hold may exist but V-Farms has not returned a confirmed reservation yet. "
                "I will not say the stay is booked. Staff will verify by the booking attempt before any retry."
            ),
            "error": str(exc),
            "timed_out": bool(getattr(exc, "timed_out", False)),
            "may_have_succeeded": bool(getattr(exc, "may_have_succeeded", False)),
            "vfarms_booking_id": booking_id,
            "vfarms_reference": reference or None,
            "attempt_key": attempt_key,
            "confirmed": False,
        }
        _save_attempt(
            db, workspace_id, attempt_key, quote_ref, "unknown", result, booking_id, reference or None
        )
        create_staff_followup(
            db,
            workspace_id=workspace_id,
            reason="confirm_uncertain",
            details={
                "quote_ref": quote_ref,
                "attempt_key": attempt_key,
                "vfarms_booking_id": booking_id,
                "error": str(exc),
            },
        )
        return result

    final_ref = str(confirmed.get("booking_reference") or reference or "").strip()
    if confirmed.get("status") == "confirmed" and final_ref:
        result = {
            "state": "confirmed",
            "speak": f"Your stay is confirmed. Your V-Farms reservation reference is {final_ref}.",
            "vfarms_booking_id": booking_id,
            "vfarms_reference": final_ref,
            "attempt_key": attempt_key,
            "confirmed": True,
            "online_payment_required": False,
            # Lead Won only from verified reservation — never from call outcome alone.
            "lead_won_eligible": True,
        }
        if quote is not None:
            quote.status = "consumed"
        _save_attempt(
            db, workspace_id, attempt_key, quote_ref, "confirmed", result, booking_id, final_ref
        )
        db.commit()
        return result

    # Hold succeeded but confirm did not prove a reservation — never say booked.
    result = {
        "state": "unknown",
        "speak": "V-Farms did not return a confirmed reservation reference. I will not say the stay is booked.",
        "vfarms_booking_id": booking_id,
        "vfarms_reference": reference or None,
        "attempt_key": attempt_key,
        "confirm_payload_status": confirmed.get("status"),
        "confirmed": False,
    }
    _save_attempt(
        db, workspace_id, attempt_key, quote_ref, "unknown", result, booking_id, reference or None
    )
    return result


def _reconcile_confirm(
    db: Session,
    *,
    workspace_id: UUID,
    attempt: VfarmsBookingAttempt,
    quote_ref: str,
) -> dict[str, Any]:
    """After timeout / unknown: retry confirm for an existing hold; never create a second hold."""
    booking_id = (attempt.vfarms_booking_id or "").strip()
    if not booking_id:
        return dict(attempt.result_payload or {"state": "unknown", "confirmed": False})

    quote = db.execute(
        select(VfarmsStayQuote).where(
            VfarmsStayQuote.workspace_id == workspace_id,
            VfarmsStayQuote.quote_ref == quote_ref,
        )
    ).scalar_one_or_none()

    return _finish_confirm(
        db,
        workspace_id=workspace_id,
        quote_ref=quote_ref,
        attempt_key=attempt.attempt_key,
        booking_id=booking_id,
        reference=(attempt.vfarms_reference or ""),
        quote=quote,
    )


def _save_attempt(
    db: Session,
    workspace_id: UUID,
    attempt_key: str,
    quote_ref: str,
    status: str,
    result: dict[str, Any],
    booking_id: str | None = None,
    reference: str | None = None,
) -> VfarmsBookingAttempt:
    row = db.execute(
        select(VfarmsBookingAttempt).where(
            VfarmsBookingAttempt.workspace_id == workspace_id,
            VfarmsBookingAttempt.attempt_key == attempt_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = VfarmsBookingAttempt(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            attempt_key=attempt_key,
            quote_ref=quote_ref,
            status=status,
            vfarms_booking_id=booking_id,
            vfarms_reference=reference,
            result_payload=result,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.execute(
                select(VfarmsBookingAttempt).where(
                    VfarmsBookingAttempt.workspace_id == workspace_id,
                    VfarmsBookingAttempt.attempt_key == attempt_key,
                )
            ).scalar_one()
            return row
    else:
        row.status = status
        row.result_payload = result
        row.vfarms_booking_id = booking_id or row.vfarms_booking_id
        row.vfarms_reference = reference or row.vfarms_reference
        db.commit()
    db.refresh(row)
    return row


def create_staff_followup(
    db: Session,
    *,
    workspace_id: UUID,
    reason: str,
    details: dict[str, Any] | None = None,
    caller_phone: str | None = None,
) -> dict[str, Any]:
    details = dict(details or {})
    details["reason"] = reason
    details["property"] = PROPERTY
    row = VoiceBookingRequest(
        workspace_id=workspace_id,
        call_id=None,
        employee_id=None,
        status="pending_staff",
        caller_phone=(caller_phone or details.get("guest_phone") or None),
        details=details,
        note=f"V-Farms staff follow-up: {reason}"[:2000],
        notify_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "state": "followup_saved",
        "speak": f"I have saved a staff follow-up. Reference {row.id}.",
        "followup_ref": str(row.id),
        "confirmed": False,
    }
