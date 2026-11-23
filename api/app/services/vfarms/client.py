"""HTTP client for the public V-Farms (vfarms.in) booking APIs."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class VfarmsApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict | None = None,
        timed_out: bool = False,
        may_have_succeeded: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}
        self.timed_out = timed_out
        self.may_have_succeeded = may_have_succeeded


def _base() -> str:
    return (get_settings().vfarms_api_base_url or "https://vfarms.in").rstrip("/")


def _json_or_empty(r: httpx.Response) -> dict[str, Any]:
    try:
        data = r.json() if r.content else {}
    except Exception:  # noqa: BLE001
        data = {}
    return data if isinstance(data, dict) else {}


def fetch_calendar(*, date_from: str, date_to: str) -> dict[str, Any]:
    url = f"{_base()}/api/availability/calendar"
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.get(url, params={"from": date_from, "to": date_to})
    except httpx.TimeoutException as exc:
        raise VfarmsApiError("calendar_timeout", timed_out=True) from exc
    data = _json_or_empty(r)
    if r.status_code >= 400:
        raise VfarmsApiError(
            str(data.get("error") or "calendar_unavailable"),
            status_code=r.status_code,
            payload=data,
        )
    return data


def fetch_quote(*, check_in: str, check_out: str, adults: int, children: int = 0) -> dict[str, Any]:
    url = f"{_base()}/api/bookings/quote"
    body = {
        "checkIn": check_in,
        "checkOut": check_out,
        "adults": adults,
        "children": children,
    }
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.post(url, json=body)
    except httpx.TimeoutException as exc:
        raise VfarmsApiError("quote_timeout", timed_out=True) from exc
    data = _json_or_empty(r)
    if r.status_code >= 400:
        raise VfarmsApiError(
            str(data.get("error") or "quote_unavailable"),
            status_code=r.status_code,
            payload=data,
        )
    return data


def create_hold(
    *,
    check_in: str,
    check_out: str,
    adults: int,
    guest_name: str,
    guest_email: str,
    guest_phone: str,
    children: int = 0,
) -> dict[str, Any]:
    """Website submit step 1 — required before confirm. Not itself a confirmation."""
    url = f"{_base()}/api/bookings/hold"
    body = {
        "checkIn": check_in,
        "checkOut": check_out,
        "adults": adults,
        "children": children,
        "guestName": guest_name,
        "guestEmail": guest_email,
        "guestPhone": guest_phone,
        "termsAccepted": True,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, json=body)
    except httpx.TimeoutException as exc:
        raise VfarmsApiError(
            "hold_timeout",
            timed_out=True,
            may_have_succeeded=True,
        ) from exc
    data = _json_or_empty(r)
    if r.status_code >= 400:
        raise VfarmsApiError(
            str(data.get("error") or "hold_failed"),
            status_code=r.status_code,
            payload=data,
        )
    return data


def confirm_booking(*, booking_id: str) -> dict[str, Any]:
    """Website submit step 2 — authoritative confirmation when status == confirmed."""
    url = f"{_base()}/api/bookings/confirm"
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, json={"bookingId": booking_id})
    except httpx.TimeoutException as exc:
        raise VfarmsApiError(
            "confirm_timeout",
            timed_out=True,
            may_have_succeeded=True,
        ) from exc
    data = _json_or_empty(r)
    if r.status_code >= 400 or data.get("status") != "confirmed":
        raise VfarmsApiError(
            str(data.get("error") or "confirm_failed"),
            status_code=r.status_code,
            payload=data,
        )
    return data


def create_event_enquiry(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base()}/api/events/enquiries"
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise VfarmsApiError("enquiry_timeout", timed_out=True) from exc
    data = _json_or_empty(r)
    if r.status_code >= 400:
        raise VfarmsApiError(
            str(data.get("error") or "enquiry_failed"),
            status_code=r.status_code,
            payload=data,
        )
    return data
