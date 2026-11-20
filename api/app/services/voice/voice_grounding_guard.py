"""Ground spoken claims in FACTS, tool results, booking state, or caller text."""

from __future__ import annotations

import re
from datetime import date

from app.services.voice.booking_state import BOOKING_KEY, load_booking
from app.services.voice.voice_fact_guard import (
    reply_asserts_ungrounded_feature,
    reply_invented_negative,
)
from app.services.voice.voice_dates import resolve_dates, today_local

_PRICE_RE = re.compile(r"(?:rs\.?|₹|inr)\s*(\d[\d,]*(?:\.\d+)?)", re.I)
_NUM_RE = re.compile(r"\b(\d{1,4})\b")
_TIME_RE = re.compile(r"\b(\d{1,2})\s*(?::\s*(\d{2}))?\s*(?:am|pm|గంటల|o'clock)?\b", re.I)
_AVAIL_RE = re.compile(
    r"(?:\d+\s*)?rooms?\s+available|available\s+rooms?|vacancy|vacant|sold\s+out|fully\s+booked|"
    r"లభ్యం|no\s+vacancy",
    re.I,
)
_HOUR_TELUGU = re.compile(r"\b(\d{1,2})\s*గంట", re.I)
_HOUR_EN = re.compile(r"\b(\d{1,2})\s*(?::\s*(\d{2}))?\s*(am|pm)\b", re.I)
_DATE_PHRASE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|nov|dec|jan)\b",
    re.I,
)
_ISO_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_RANGE_RE = re.compile(
    r"(?:from|నుంచి|నుండి)\s+.+?\s+(?:to|వరకు|until)",
    re.I,
)
_PRECONFIRM_COMMIT = re.compile(
    r"(బుక్\s*చేస్త|book\s*(?:it|చే)|check-?in\s*చేస్త|check-?in\s*చే(?:ద్దాం|స్త))",
    re.I,
)
_MULTI_SLOT = re.compile(
    r"(ఎన్ని\s*nights.{0,40}(ఎంత\s*మంది|guests)|"
    r"(ఎంత\s*మంది|guests).{0,40}ఎన్ని\s*nights)",
    re.I | re.S,
)

_MONTH = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _corpus_parts(
    *,
    spoken_facts: str,
    fields: dict,
    caller_text: str,
) -> str:
    parts = [spoken_facts or "", caller_text or ""]
    st = load_booking(fields)
    if st.check_in:
        parts.append(st.check_in)
    _, cout_c = _caller_resolved_dates(caller_text, fields)
    if cout_c:
        parts.append(cout_c)
    if st.guest_count:
        parts.append(str(st.guest_count))
    for row in fields.get("tool_log") or []:
        if isinstance(row, dict):
            parts.append(str(row.get("spoken") or ""))
            parts.append(str(row.get("result") or ""))
    parts.append(str(fields.get("last_tool_spoken") or ""))
    for t in resolve_dates(caller_text, anchor=today_local()).notes or []:
        parts.append(t)
    r = resolve_dates(caller_text, anchor=today_local())
    if r.check_in:
        parts.append(r.check_in)
    if r.check_out:
        parts.append(r.check_out)
    return "\n".join(parts)


def _availability_ok(fields: dict) -> bool:
    if fields.get("availability_not_configured"):
        return False
    lt = str(fields.get("last_tool") or "")
    if "not_configured" in lt or "unavailable" in lt:
        return False
    st = load_booking(fields)
    if st.availability_status and st.availability_status != "available":
        return False
    if fields.get("availability_status") and fields.get("availability_status") != "available":
        return False
    return fields.get("availability_status") == "available" or (
        load_booking(fields).availability_status == "available"
    )


def _time_claims_grounded(sentence: str, corpus: str) -> bool:
    corp = corpus or ""
    for m in _HOUR_TELUGU.finditer(sentence):
        hour = m.group(1)
        if not re.search(rf"\b{re.escape(hour)}\s*గంట", corp, re.I):
            return False
    for m in _HOUR_EN.finditer(sentence):
        hour, _mins, ampm = m.group(1), m.group(2), m.group(3)
        if not re.search(rf"\b{re.escape(hour)}\s*(?::\s*\d{{2}})?\s*{re.escape(ampm)}\b", corp, re.I):
            return False
    return True


def _allowed_numbers(corpus: str, caller: str, fields: dict) -> set[str]:
    allowed: set[str] = set()
    for m in _NUM_RE.finditer(corpus):
        allowed.add(m.group(1))
    for m in _NUM_RE.finditer(caller or ""):
        allowed.add(m.group(1))
    st = load_booking(fields)
    if st.guest_count:
        allowed.add(str(st.guest_count))
    for amt in _PRICE_RE.findall(corpus):
        allowed.add(amt.replace(",", ""))
    return allowed


_TE_MONTH = {
    "జనవరి": 1,
    "ఫిబ్రవరి": 2,
    "మార్చి": 3,
    "ఏప్రిల్": 4,
    "మే": 5,
    "జూన్": 6,
    "జులై": 7,
    "ఆగస్టు": 8,
    "సెప్టెంబర్": 9,
    "అక్టోబర్": 10,
    "నవంబర్": 11,
    "డిసెంబర్": 12,
}
_TE_DATE = re.compile(
    r"(\d{1,2})(?:వ)?\s*(జనవరి|ఫిబ్రవరి|మార్చి|ఏప్రిల్|మే|జూన్|జులై|ఆగస్టు|సెప్టెంబర్|అక్టోబర్|నవంబర్|డిసెంబర్)",
    re.I,
)


def _reply_dates_iso(reply: str, anchor: date) -> set[str]:
    found: set[str] = set()
    for m in _ISO_RE.finditer(reply):
        found.add(m.group(1))
    for m in _DATE_PHRASE.finditer(reply):
        day = int(m.group(1))
        mo = _MONTH.get(m.group(2).lower(), anchor.month)
        try:
            found.add(date(anchor.year, mo, day).isoformat())
        except ValueError:
            pass
    for m in _TE_DATE.finditer(reply):
        day = int(m.group(1))
        mo = _TE_MONTH.get(m.group(2), anchor.month)
        try:
            found.add(date(anchor.year, mo, day).isoformat())
        except ValueError:
            pass
    return found


_SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")


def apply_grounding_to_reply(
    reply: str,
    *,
    spoken_facts: str,
    fields: dict,
    caller_text: str,
) -> tuple[str, list[str]]:
    """Drop ungrounded sentences; if none left, return confirm line."""
    text = (reply or "").strip()
    if not text:
        return text, []
    reasons: list[str] = []
    lang = str(fields.get("conversation_language") or "te-IN")
    parts = _SENT_SPLIT.split(text) if _SENT_SPLIT.search(text) else [text]
    kept: list[str] = []
    for part in parts:
        p = part.strip()
        if not p:
            continue
        fail, rs = sentence_fails_grounding(
            p, spoken_facts=spoken_facts, fields=fields, caller_text=caller_text
        )
        if fail:
            reasons.extend(rs)
            continue
        kept.append(p)
    if kept:
        return " ".join(kept), reasons
    return confirm_save_lead_line(lang), reasons


def _caller_corpus(caller: str, fields: dict) -> str:
    parts = [caller or ""]
    chat = fields.get("inbound_chat") or {}
    for row in chat.get("turns") or []:
        if isinstance(row, dict) and row.get("caller"):
            parts.append(str(row["caller"]))
    return " ".join(parts)


def _caller_resolved_dates(caller: str, fields: dict) -> tuple[str | None, str | None]:
    anchor = today_local()
    r = resolve_dates(_caller_corpus(caller, fields), anchor=anchor)
    return r.check_in, r.check_out


def _allowed_dates_iso(corpus: str, caller: str, fields: dict) -> set[str]:
    anchor = today_local()
    allowed: set[str] = set()
    for m in _ISO_RE.finditer(corpus):
        allowed.add(m.group(1))
    st = load_booking(fields)
    if st.check_in:
        allowed.add(st.check_in)
    cin_c, cout_c = _caller_resolved_dates(caller, fields)
    if cin_c:
        allowed.add(cin_c)
    if cout_c:
        allowed.add(cout_c)
    r = resolve_dates(caller, anchor=anchor)
    if r.check_in:
        allowed.add(r.check_in)
    if r.check_out:
        allowed.add(r.check_out)
    return allowed


def sentence_fails_grounding(
    sentence: str,
    *,
    spoken_facts: str,
    fields: dict,
    caller_text: str,
) -> tuple[bool, list[str]]:
    """True if sentence must not be spoken (ungrounded claim)."""
    reasons: list[str] = []
    t = (sentence or "").strip()
    if not t:
        return False, []
    low = t.lower()
    corpus = _corpus_parts(spoken_facts=spoken_facts, fields=fields, caller_text=caller_text)
    corpus_low = corpus.lower()
    st = load_booking(fields)

    if _AVAIL_RE.search(t) and not _availability_ok(fields):
        tool_line = str(fields.get("last_tool_spoken") or "")
        if not (tool_line and t.strip() in tool_line):
            reasons.append("availability_ungrounded")

    prices = {x.replace(",", "") for x in _PRICE_RE.findall(t)}
    if prices:
        fact_prices = {x.replace(",", "") for x in _PRICE_RE.findall(spoken_facts)}
        if not prices.issubset(fact_prices) and not prices.issubset(_allowed_numbers(corpus, caller_text, fields)):
            reasons.append("price_ungrounded")

    if _HOUR_TELUGU.search(t) or _HOUR_EN.search(t) or _TIME_RE.search(t):
        if not _time_claims_grounded(t, corpus):
            reasons.append("time_ungrounded")

    reply_dates = _reply_dates_iso(t, today_local())
    allowed_dates = _allowed_dates_iso(corpus, caller_text, fields)
    extra = reply_dates - allowed_dates
    if extra:
        reasons.append("date_ungrounded")

    if _RANGE_RE.search(t) and st.check_in and not st.check_out:
        if re.search(r"(వరకు|to\s+\d|until)", t, re.I):
            reasons.append("checkout_without_state")

    nums_in_reply = {m.group(1) for m in _NUM_RE.finditer(t)}
    guest_claims = nums_in_reply - _allowed_numbers(corpus, caller_text, fields)
    if guest_claims and st.guest_count and any(int(x) > 20 for x in guest_claims if x.isdigit()):
        reasons.append("count_ungrounded")

    if reply_asserts_ungrounded_feature(t, spoken_facts):
        reasons.append("amenity_ungrounded")
    if reply_invented_negative(t, spoken_facts):
        reasons.append("invented_negative")

    if not st.booking_confirmed and not st.awaiting_confirmation:
        if _PRECONFIRM_COMMIT.search(t) and "పెట్టమంటారా" not in t:
            reasons.append("pre_confirm_commitment")
        if _MULTI_SLOT.search(t):
            reasons.append("multi_slot_question")

    return bool(reasons), reasons


def confirm_save_lead_line(lang: str) -> str:
    if lang == "te-IN":
        return "confirm చేసి చెప్తాము అండి — మా team మీ ప్రశ్న note చేస్తారు."
    return "We'll confirm and get back to you — I've noted your question."


def booking_date_readback(st, *, lang: str) -> str:
    """Speak dates only from booking state ISO."""
    if not st.check_in:
        return ""
    cin = st.check_in
    if lang == "te-IN":
        d = date.fromisoformat(cin)
        base = f"{d.day} {d.strftime('%B')} check-in"
        if st.check_out:
            o = date.fromisoformat(st.check_out)
            return f"{base}, {o.day} {o.strftime('%B')} check-out"
        return f"{base} — ఎన్ని nights అండి?"
    if st.check_out:
        return f"check-in {cin}, check-out {st.check_out}"
    return f"check-in {cin} — how many nights?"