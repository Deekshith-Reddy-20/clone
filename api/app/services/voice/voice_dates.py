"""Relative spoken dates in Asia/Kolkata — LLM must not compute dates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Kolkata")

_TE_WEEKDAY = {
    "సోమవారం": 0,
    "సోమ": 0,
    "మంగళవారం": 1,
    "మంగళ": 1,
    "బుధవారం": 2,
    "బుధ": 2,
    "గురువారం": 3,
    "గురు": 3,
    "శుక్రవారం": 4,
    "శుక్ర": 4,
    "శనివారం": 5,
    "శని": 5,
    "ఆదివారం": 6,
    "ఆది": 6,
}

_EN_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

_WEEKDAY_LABEL = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKDAY_TE = ("సోమ", "మంగళ", "బుధ", "గురు", "శుక్ర", "శని", "ఆది")


def today_local(anchor: date | None = None) -> date:
    if anchor is not None:
        return anchor
    from datetime import datetime

    return datetime.now(_TZ).date()


def _this_weekday(base: date, weekday: int) -> date:
    delta = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta)


def _next_weekday(base: date, weekday: int) -> date:
    d = _this_weekday(base, weekday)
    if d <= base:
        d += timedelta(days=7)
    return d


@dataclass
class ResolvedStay:
    check_in: str | None = None
    check_out: str | None = None
    nights: int | None = None
    notes: list[str] | None = None


def resolve_dates(text: str, *, anchor: date | None = None) -> ResolvedStay:
    """Parse caller text into ISO check-in/out without LLM."""
    t = (text or "").strip()
    out = ResolvedStay(notes=[])
    if not t:
        return out
    base = today_local(anchor)
    low = t.lower()
    check_in: date | None = None
    check_out: date | None = None
    nights: int | None = None

    if re.search(r"ఈ\s*రోజు|today", low):
        check_in = base
        out.notes.append("ఈ రోజు")
    if re.search(r"రేపు|రేపటి|tomorrow", low) and "ఎల్లుండి" not in t:
        check_in = base + timedelta(days=1)
        out.notes.append("రేపు")
    if "ఎల్లుండి" in t or "day after tomorrow" in low:
        check_in = base + timedelta(days=2)
        out.notes.append("ఎల్లుండి")

    for key, wd in _TE_WEEKDAY.items():
        if key not in t:
            continue
        if "వచ్చే" in t or "next" in low:
            target = _next_weekday(base, wd)
        elif "ఈ" in t[: key.find(key) + 3] or "this" in low:
            target = _this_weekday(base, wd)
            if target < base:
                target = _next_weekday(base, wd)
        else:
            target = _next_weekday(base, wd)
        if check_in is None:
            check_in = target
        elif check_out is None and target != check_in:
            check_out = target
        out.notes.append(key)

    for key, wd in _EN_WEEKDAY.items():
        if re.search(rf"\b{re.escape(key)}\b", low):
            target = _next_weekday(base, wd) if "next" in low else _this_weekday(base, wd)
            if target < base:
                target = _next_weekday(base, wd)
            if check_in is None:
                check_in = target
            elif check_out is None:
                check_out = target

    if "next weekend" in low:
        sat = _next_weekday(base, 5)
        check_in = check_in or sat
        check_out = check_out or sat + timedelta(days=1)
    if "this weekend" in low:
        sat = _this_weekday(base, 5)
        if sat < base:
            sat = _next_weekday(base, 5)
        check_in = check_in or sat
        check_out = check_out or sat + timedelta(days=1)

    m = re.search(r"(\d{1,2})\s*(?:to|-)\s*(\d{1,2})", low)
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        for day, slot in ((d1, "in"), (d2, "out")):
            try:
                cand = base.replace(day=day)
                if cand < base - timedelta(days=2):
                    cand = date(base.year, base.month + 1, day) if base.month < 12 else date(base.year + 1, 1, day)
                if slot == "in" and check_in is None:
                    check_in = cand
                elif slot == "out" and check_out is None:
                    check_out = cand
            except ValueError:
                pass

    m_nights = re.search(r"(\d{1,2})\s*(?:nights?|రాత్రులు|నైట్)", low)
    if m_nights:
        nights = int(m_nights.group(1))

    for m in re.finditer(r"\b(november|nov|december|dec)\s+(\d{1,2})\b", low):
        month_map = {"nov": 11, "november": 11, "dec": 12, "december": 12}
        mo = month_map.get(m.group(1), base.month)
        day = int(m.group(2))
        try:
            cand = date(base.year, mo, day)
            if check_in is None:
                check_in = cand
            elif check_out is None:
                check_out = cand
        except ValueError:
            pass

    if check_in and nights and not check_out:
        check_out = check_in + timedelta(days=nights)
    if check_in:
        out.check_in = check_in.isoformat()
    if check_out:
        out.check_out = check_out.isoformat()
    out.nights = nights
    return out


def parse_spoken_dates(text: str, *, anchor: date | None = None) -> list[str]:
    """Return ISO dates mentioned or implied (legacy helper)."""
    r = resolve_dates(text, anchor=anchor)
    found: list[str] = []
    if r.check_in:
        found.append(r.check_in)
    if r.check_out and r.check_out not in found:
        found.append(r.check_out)
    return sorted(found)


def calendar_block_for_prompt(*, anchor: date | None = None, days: int = 14) -> str:
    base = today_local(anchor)
    lines = [f"Today {_WEEKDAY_LABEL[base.weekday()]} {base.day} {base.strftime('%b %Y')} (call local date)."]
    rel = (
        (1, "tomorrow (రేపు)"),
        (2, "day after (ఎల్లుండి)"),
    )
    for offset, label in rel:
        d = base + timedelta(days=offset)
        lines.append(f"{label}: {_WEEKDAY_LABEL[d.weekday()]} {d.day} {d.strftime('%b')}")
    for i in range(days):
        d = base + timedelta(days=i)
        te = _WEEKDAY_TE[d.weekday()]
        lines.append(f"+{i}d {te} {_WEEKDAY_LABEL[d.weekday()]} {d.day} {d.strftime('%b')} = {d.isoformat()}")
    lines.append("Read check-in/out ONLY from call_state ISO dates — never invent weekdays/months.")
    return "\n".join(lines)


def apply_resolved_dates_to_booking(fields: dict, caller_text: str, *, anchor: date | None = None) -> dict:
    from app.services.voice.booking_state import BOOKING_KEY, dump_booking, load_booking

    st = load_booking(fields)
    resolved = resolve_dates(caller_text, anchor=anchor)
    if resolved.check_in:
        st.check_in = resolved.check_in
        st.check_in_confirmed = True
        st.check_in_day = date.fromisoformat(resolved.check_in).day
        st.day_only_range = False
        st.month_confirmed = True
    if resolved.check_out:
        st.check_out = resolved.check_out
        st.check_out_day = date.fromisoformat(resolved.check_out).day
    if resolved.nights and st.check_in and not st.check_out:
        ci = date.fromisoformat(st.check_in)
        st.check_out = (ci + timedelta(days=resolved.nights)).isoformat()
        st.check_out_day = date.fromisoformat(st.check_out).day
    fields[BOOKING_KEY] = dump_booking(st)
    return fields