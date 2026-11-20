"""Hospital OP appointment state on inbound Call.captured_fields."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.voice.booking_state import (
    _day_to_iso,
    extract_dates,
    extract_phone,
    format_date_spoken,
)

APPOINTMENT_KEY = "inbound_appointment"


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass
class AppointmentState:
    department: str | None = None
    preferred_date: str | None = None  # ISO
    preferred_day: int | None = None
    preferred_time: str | None = None
    callback_phone: str | None = None
    last_prompt: str | None = None
    lookup_status: str | None = None  # pending | available | booked | unavailable
    booking_ref: str | None = None
    booking_confirmed: bool = False
    awaiting_confirmation: bool = False

    def to_dict(self) -> dict:
        return {
            "department": self.department,
            "preferred_date": self.preferred_date,
            "preferred_day": self.preferred_day,
            "preferred_time": self.preferred_time,
            "callback_phone": self.callback_phone,
            "last_prompt": self.last_prompt,
            "lookup_status": self.lookup_status,
            "booking_ref": self.booking_ref,
            "booking_confirmed": self.booking_confirmed,
            "awaiting_confirmation": self.awaiting_confirmation,
        }


def load_appointment(fields: dict) -> AppointmentState:
    raw = fields.get(APPOINTMENT_KEY)
    if not isinstance(raw, dict):
        return AppointmentState()
    return AppointmentState(
        department=_str_or_none(raw.get("department")),
        preferred_date=_str_or_none(raw.get("preferred_date")),
        preferred_day=raw.get("preferred_day") if raw.get("preferred_day") is not None else None,
        preferred_time=_str_or_none(raw.get("preferred_time")),
        callback_phone=_str_or_none(raw.get("callback_phone")),
        last_prompt=_str_or_none(raw.get("last_prompt")),
        lookup_status=_str_or_none(raw.get("lookup_status")),
        booking_ref=_str_or_none(raw.get("booking_ref")),
        booking_confirmed=bool(raw.get("booking_confirmed")),
        awaiting_confirmation=bool(raw.get("awaiting_confirmation")),
    )


def dump_appointment(state: AppointmentState) -> dict:
    return state.to_dict()


_DEPT_RE = re.compile(
    r"(cardiology|orthop|dermat|pediat|gynae|general medicine|neuro|ent|ophthal)",
    re.I,
)


def extract_department(text: str) -> str | None:
    m = _DEPT_RE.search(text or "")
    if m:
        return m.group(1).title()
    te = text or ""
    if "జనరల్" in te or "general" in (text or "").lower():
        return "General Medicine"
    return None


def extract_time_hint(text: str) -> str | None:
    m = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))", text or "")
    if m:
        return m.group(1).upper().replace(" ", "")
    if "మధ్యాహ్న" in (text or ""):
        return "afternoon"
    if "ఉదయం" in (text or ""):
        return "morning"
    return None


def merge_appointment_utterance(state: AppointmentState, text: str) -> AppointmentState:
    t = (text or "").strip()
    if not t:
        return state
    dept = extract_department(t)
    if dept:
        state.department = dept
    cin, _ = extract_dates(t)
    if cin:
        state.preferred_date = cin
    else:
        for n in re.findall(r"\b(\d{1,2})\b", t):
            d = int(n)
            if 1 <= d <= 31:
                iso = _day_to_iso(d)
                if iso:
                    state.preferred_date = iso
                    state.preferred_day = d
                    break
    if "రేపు" in t and not state.preferred_date:
        from datetime import date, timedelta

        state.preferred_date = (date.today() + timedelta(days=1)).isoformat()
    tm = extract_time_hint(t)
    if tm:
        state.preferred_time = tm
    phone = extract_phone(t)
    if phone:
        state.callback_phone = phone
    return state


def missing_appointment_fields(state: AppointmentState) -> list[str]:
    miss: list[str] = []
    if not state.department:
        miss.append("department")
    if not state.preferred_date:
        miss.append("date")
    if not state.callback_phone:
        miss.append("phone")
    return miss


def appointment_summary(state: AppointmentState, lang: str) -> str:
    parts: list[str] = []
    if state.department:
        parts.append(state.department)
    if state.preferred_date:
        parts.append(format_date_spoken(state.preferred_date, lang))
    if state.preferred_time:
        parts.append(state.preferred_time)
    return ", ".join(parts)