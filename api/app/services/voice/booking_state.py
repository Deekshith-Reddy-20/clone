"""Per-call resort booking fields (V Farms and similar). Pure logic — no I/O."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

BOOKING_KEY = "inbound_booking"


def booking_intent_utterance(text: str) -> bool:
    low = (text or "").lower()
    te = text or ""
    return any(
        p in low or p in te
        for p in (
            "availability",
            "available",
            "book",
            "booking",
            "అవైలబిలిటీ",
            "బుక్",
            "reservation",
        )
    )


@dataclass
class BookingState:
    check_in: str | None = None  # ISO YYYY-MM-DD
    check_out: str | None = None
    guest_count: int | None = None
    guest_name: str | None = None
    callback_phone: str | None = None
    availability_summary: str | None = None
    availability_status: str | None = None  # available | unavailable | pending
    booking_ref: str | None = None
    booking_confirmed: bool = False
    lookup_in_progress: bool = False
    partial_phone: str | None = None
    phone_declined: bool = False
    awaiting_confirmation: bool = False
    last_utterance_hash: str | None = None
    updated_at: str | None = None
    last_prompt: str | None = None  # month | check_in | check_out | guests | confirm_checkout
    day_only_range: bool = False
    month_confirmed: bool = False
    pending_confirm_field: str | None = None
    pending_confirm_day: int | None = None
    check_in_day: int | None = None
    check_out_day: int | None = None
    check_in_confirmed: bool = False
    nights: int | None = None
    last_slot_asked: str | None = None


def load_booking(fields: dict | None) -> BookingState:
    raw = (fields or {}).get(BOOKING_KEY)
    if not isinstance(raw, dict):
        return BookingState()
    return BookingState(
        check_in=_str_or_none(raw.get("check_in")),
        check_out=_str_or_none(raw.get("check_out")),
        guest_count=_int_or_none(raw.get("guest_count")),
        guest_name=_str_or_none(raw.get("guest_name")),
        callback_phone=_str_or_none(raw.get("callback_phone")),
        availability_summary=_str_or_none(raw.get("availability_summary")),
        availability_status=_str_or_none(raw.get("availability_status")),
        booking_ref=_str_or_none(raw.get("booking_ref")),
        booking_confirmed=bool(raw.get("booking_confirmed")),
        lookup_in_progress=bool(raw.get("lookup_in_progress")),
        partial_phone=_str_or_none(raw.get("partial_phone")),
        phone_declined=bool(raw.get("phone_declined")),
        awaiting_confirmation=bool(raw.get("awaiting_confirmation")),
        last_utterance_hash=_str_or_none(raw.get("last_utterance_hash")),
        updated_at=_str_or_none(raw.get("updated_at")),
        last_prompt=_str_or_none(raw.get("last_prompt")),
        day_only_range=bool(raw.get("day_only_range")),
        month_confirmed=bool(raw.get("month_confirmed")),
        pending_confirm_field=_str_or_none(raw.get("pending_confirm_field")),
        pending_confirm_day=_int_or_none(raw.get("pending_confirm_day")),
        check_in_day=_int_or_none(raw.get("check_in_day")),
        check_out_day=_int_or_none(raw.get("check_out_day")),
        check_in_confirmed=bool(raw.get("check_in_confirmed")),
        nights=_int_or_none(raw.get("nights")),
        last_slot_asked=_str_or_none(raw.get("last_slot_asked")),
    )


def dump_booking(state: BookingState) -> dict:
    return {k: v for k, v in asdict(state).items() if v is not None}


def _str_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int_or_none(v: object) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def utterance_fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:240]


def is_duplicate_utterance(state: BookingState, text: str) -> bool:
    fp = utterance_fingerprint(text)
    return bool(fp and state.last_utterance_hash == fp)


def _reference_today() -> date:
    return datetime.now(IST).date()


_TELUGU_DIGITS = str.maketrans("౦౧౨౩౪౫౬౭౮౯", "0123456789")


def _normalize_text(text: str) -> str:
    t = text.translate(_TELUGU_DIGITS)
  # Telugu number words (common on calls)
    t = re.sub(r"\bపదహైదు\b", "15", t, flags=re.I)
    t = re.sub(r"\bపది\b", "10", t, flags=re.I)
    t = re.sub(r"\bఇరవై\b", "20", t, flags=re.I)
    t = re.sub(r"ముప్పై\s*(?:అయిదు|ఐదు)", "35", t)
    t = re.sub(r"ముప్పై(?:అయిదు|ఐదు)", "35", t)
    t = re.sub(r"\bthirty[\s\-]*five\b", "35", t, flags=re.I)
    t = re.sub(r"पैंतीस|पैंतीस", "35", t)
    t = re.sub(r"\bముప్పై\b", "30", t)
    t = re.sub(r"\bత్రైపంచ(?:వ|)?\b", "35", t, flags=re.I)
    t = re.sub(r"\bఇరవై\s*ఐదో\b", "25th", t, flags=re.I)
    t = re.sub(r"\bఇరవై\s*ఐదు\b", "25", t, flags=re.I)
    t = re.sub(r"\bఇరవై\s*ఒకటి\b", "21", t, flags=re.I)
    t = re.sub(r"\bఇరవై\s*రెండు\b", "22", t, flags=re.I)
    t = re.sub(r"\bఇరవై\s*మూడు\b", "23", t, flags=re.I)
    t = re.sub(r"\bపదిహేన\b|\bపదహేన\b", "15", t, flags=re.I)
    t = re.sub(r"\bपंद्रह\b", "15", t, flags=re.I)
    t = re.sub(r"\bदस\b", "10", t, flags=re.I)
    t = re.sub(r"\bबीस\b", "20", t, flags=re.I)
    return t


_GUEST_RE = re.compile(
    r"(?:(\d{1,3})\s*(?:members?|guests?|people|persons?|mandi|మంది|మెంబర్|మెంబర్స్|लोग|मेहमान)"
    r"|(?:total|మొత్తం)\s*(\d{1,3})\s*(?:members?|guests?|people|mandi|మంది|మెంబర్|लोग)?"
    r"|(\d{1,3})\s*(?:మంది|లో|लोग|मेहमान)(?:\s*దాకా)?"
    r"|(?:for\s+)?(\d{1,3})\s+guests"
    r"|(\d{1,2})\s*(?:వస్తారు|వస్తాము|గురం|గురు)"
    r"|(?:నలుగురు|అయిదుగురు|ఆరుగురు|ఏడుగురు|ఎనిమిదిగురు|తొమ్మిదిగురు|పదిమంది)"
    r"|(?:ఒక|और|about)\s*(\d{1,3})\s*(?:మంది|लोग)?"
    r"|पंद्रह\s*(?:लोग|मेहमान)?)",
    re.I,
)

_PHONE_RE = re.compile(
    r"(?:\+91[\s\-]?)?([6-9]\d{9})|(?:phone|mobile|నంబర్|నంబరు|కాల్)\s*(?:number)?\s*[:\-]?\s*(\d{10})",
    re.I,
)

_DATE_HINT_RE = re.compile(
    r"(check[\s\-]?in|చెక్[\s\-]?ఇన్|చెక్ ఇన్|లోగిన్)\D{0,24}(\d{1,2})",
    re.I,
)
_DATE_HINT_OUT_RE = re.compile(
    r"(check[\s\-]?out|చెక్[\s\-]?ఔట్|చెక్ ఔట్|లాగౌట్)\D{0,24}(\d{1,2})",
    re.I,
)
_DAY_TARIKH_RE = re.compile(r"(\d{1,2})\s*(?:తారీఖు|తేదీ|date)", re.I)
_PAIR_RE = re.compile(
    r"(\d{1,2})\s*(?:నుంచి|నుండి|from|to|వరకు|until|-)\s*(\d{1,2})",
    re.I,
)
_ORDINAL_DAY_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)\b|(\d{1,2})\s*(?:వ|వు)?\s*(?:తారీఖు|తేదీ)",
    re.I,
)
_MONTH_NAMES = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"జనవరి|ఫిబ్రవరి|మార్చి|ఏప్రిల్|మే|జూన్|జులై|ఆగస్టు|సెప్టెంబర్|అక్టోబర్|నవంబర్|డిసెంబర్|"
    r"जनवरी|फ़रवरी|मार्च|अप्रैल|मई|जून|जुलाई|अगस्त|सितंबर|अक्टूबर|नवंबर|दिसंबर)",
    re.I,
)
_STANDALONE_DAYS = re.compile(r"\b(\d{1,2})\b")


def _day_to_iso(day: int, ref: date | None = None) -> str:
    today = ref or _reference_today()
    try:
        candidate = date(today.year, today.month, day)
    except ValueError:
        return ""
    if candidate < today - timedelta(days=2):
        if today.month == 12:
            candidate = date(today.year + 1, 1, day)
        else:
            try:
                candidate = date(today.year, today.month + 1, day)
            except ValueError:
                candidate = date(today.year + 1, today.month, day)
    return candidate.isoformat()


_TE_GUEST_WORDS = {
    "నలుగురు": 4,
    "అయిదుగురు": 5,
    "ఆరుగురు": 6,
    "ఏడుగురు": 7,
    "ఎనిమిదిగురు": 8,
    "తొమ్మిదిగురు": 9,
    "పదిమంది": 10,
}


def extract_guest_count(text: str) -> int | None:
    t = _normalize_text(text)
    raw = text or ""
    for word, n in _TE_GUEST_WORDS.items():
        if word in raw:
            return n
    for m in _GUEST_RE.finditer(t):
        for g in m.groups():
            if g and str(g).isdigit():
                n = int(g)
                if 1 <= n <= 99:
                    return n
    return None


def _without_long_digits(text: str) -> str:
    """4+ digit runs are phone fragments, not calendar days."""
    return re.sub(r"\d{4,}", " ", text or "")


def extract_dates(text: str) -> tuple[str | None, str | None]:
    t = _normalize_text(_without_long_digits(text))
    check_in: str | None = None
    check_out: str | None = None
    guest_n = extract_guest_count(text)

    m = _DATE_HINT_RE.search(t)
    if m:
        check_in = _day_to_iso(int(m.group(2)))
    m = _DATE_HINT_OUT_RE.search(t)
    if m:
        check_out = _day_to_iso(int(m.group(2)))

    if not check_in or not check_out:
        pm = _PAIR_RE.search(t)
        if pm:
            d1, d2 = int(pm.group(1)), int(pm.group(2))
            if not check_in:
                check_in = _day_to_iso(d1)
            if not check_out:
                check_out = _day_to_iso(d2)

    days = [int(x) for x in _STANDALONE_DAYS.findall(t) if 1 <= int(x) <= 31]
    if guest_n is not None:
        days = [d for d in days if d != guest_n]
    tarikhs = [int(x) for x in _DAY_TARIKH_RE.findall(t)]
    days.extend(tarikhs)
    for om in _ORDINAL_DAY_RE.finditer(t):
        for g in om.groups():
            if g:
                d = int(g)
                if 1 <= d <= 31 and d not in days:
                    days.append(d)
    if days:
        days = sorted(set(days))
        if not check_in and len(days) >= 1:
            check_in = _day_to_iso(days[0])
        if not check_out and len(days) >= 2:
            check_out = _day_to_iso(days[1])
        elif not check_out and len(days) == 1 and check_in:
            pass

    if check_in and check_out and check_in >= check_out:
        # Same-day typo: treat second as checkout if later day number
        d_in = date.fromisoformat(check_in)
        d_out = date.fromisoformat(check_out)
        if d_out <= d_in:
            check_out = (d_in + timedelta(days=1)).isoformat()
    return check_in or None, check_out or None


def _extract_partial_phone(text: str) -> str | None:
    raw = text or ""
    keyed = re.search(r"(?:నంబర్|నంబరు|phone|mobile)\D{0,8}(\d{4,10})", raw, re.I)
    if keyed:
        frag = keyed.group(1)
        if len(frag) == 10 and frag[0] in "6789":
            return None
        return frag
    embedded = re.search(r"(?<!\d)([6-9]\d{3,8})(?!\d)", raw)
    if embedded:
        frag = embedded.group(1)
        if len(frag) == 10:
            return None
        return frag
    compact = re.sub(r"\s+", "", raw)
    if re.fullmatch(r"\d{4,9}", compact) and compact[0] in "6789":
        return compact
    if re.fullmatch(r"\d{3,6}", compact):
        return compact
    return None


def extract_phone(text: str) -> str | None:
    t = _normalize_text(text)
    m = _PHONE_RE.search(t)
    if not m:
        return None
    for g in m.groups():
        if g:
            return g
    return None


def apply_corrections(state: BookingState, text: str) -> BookingState:
    t = text.lower()
    if "not " in t or "కాదు" in t or "లేదు" in t:
        m = re.search(r"(\d{1,2})\s*(?:కాదు|not)", text)
        if m and state.check_out:
            state.check_out = None
        m = re.search(r"(\d{1,2})\s*(?:instead|కు|గా)", text)
        if m:
            day = int(m.group(1))
            if "checkout" in t or "ఔట్" in t:
                state.check_out = _day_to_iso(day)
            elif "check" in t or "ఇన్" in t:
                check_in = _day_to_iso(day)
                if check_in:
                    state.check_in = check_in
    return state


def _bare_day_numbers(text: str) -> list[int]:
    t = _normalize_text(_without_long_digits(text)).strip()
    guest_n = extract_guest_count(text)
    nums = [int(x) for x in re.findall(r"\d{1,2}", t) if 1 <= int(x) <= 31]
    if guest_n is not None:
        nums = [n for n in nums if n != guest_n]
    return nums


def is_incomplete_caller_utterance(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.endswith(("…", "...", "–", "-")):
        return True
    if "ఎల్లుండి" in t and len(t) < 48 and "availability" not in t.lower() and "అవైలబిలిటీ" not in t:
        return True
    return False


def is_confusion_prompt(text: str) -> bool:
    raw = (text or "").strip()
    t = raw.lower()
    te = raw
    return any(
        p in t or p in te
        for p in (
            "ఏం చెప్పాలి",
            "ఏం విషయం చెప్పాలి",
            "ఏమి చెప్పాలి",
            "what should i say",
            "what do i say",
            "కన్ఫ్యూజ్",
            "అర్థం కాలేదు",
        )
    )


def is_negation_utterance(text: str) -> bool:
    raw = text or ""
    low = raw.lower()
    return "లేదు" in raw or "కాదు" in raw or "not " in low or " instead" in low


def is_explicit_date_correction(text: str) -> bool:
    low = (text or "").lower()
    te = text or ""
    return any(
        p in low or p in te
        for p in (
            "checkout",
            "check out",
            "check-in",
            "check in",
            "ఔట్",
            "చెక్-ఔట్",
            "చెక్ ఔట్",
            "చెక్-ఇన్",
            "చెక్ ఇన్",
            "ఇన్",
            "కాదు",
            "మార్చ",
            "instead",
        )
    )


def explicit_check_in_day(text: str) -> int | None:
    t = _normalize_text(_without_long_digits(text))
    if "లేదు" in text or "కాదు" in text:
        if re.search(r"check[\s\-]?in|చెక్[\s\-]?ఇన్|చెక్\s*ఇన్", t, re.I):
            for om in _ORDINAL_DAY_RE.finditer(t):
                for g in om.groups():
                    if g:
                        return int(g)
            days = [int(x) for x in _STANDALONE_DAYS.findall(t) if 1 <= int(x) <= 31]
            if len(days) == 1:
                return days[0]
    m = _DATE_HINT_RE.search(t)
    if m:
        d = int(m.group(2))
        if 1 <= d <= 31:
            return d
    if re.search(r"check[\s\-]?in|చెక్[\s\-]?ఇన్|చెక్\s*ఇన్", t, re.I):
        for om in _ORDINAL_DAY_RE.finditer(t):
            for g in om.groups():
                if g:
                    return int(g)
        days = [int(x) for x in _STANDALONE_DAYS.findall(t) if 1 <= int(x) <= 31]
        if len(days) == 1:
            return days[0]
    return None


def explicit_check_out_day(text: str) -> int | None:
    t = _normalize_text(_without_long_digits(text))
    m = _DATE_HINT_OUT_RE.search(t)
    if m:
        d = int(m.group(2))
        if 1 <= d <= 31:
            return d
    if re.search(r"check[\s\-]?out|చెక్[\s\-]?ఔట్|చెక్\s*ఔట్", t, re.I):
        days = [int(x) for x in _STANDALONE_DAYS.findall(t) if 1 <= int(x) <= 31]
        if len(days) == 1:
            return days[0]
    return None


def is_bare_negation_only(text: str) -> bool:
    """Negation with no date, day, or field — must not alter booking state."""
    if not is_negation_utterance(text):
        return False
    if single_day_in_utterance(text) is not None:
        return False
    if explicit_check_in_day(text) is not None or explicit_check_out_day(text) is not None:
        return False
    if re.search(r"\d{1,2}", text or ""):
        return False
    stripped = re.sub(
        r"లేదు|కాదు|no\b|not\b",
        "",
        (text or ""),
        flags=re.I,
    ).strip(" .,!?:;…-")
    return len(stripped) < 4


_TELUGU_SPOKEN_DAY = (
    (re.compile(r"ఇరవై\s*ఐదో"), 25),
    (re.compile(r"ఇరవై\s*ఐదు"), 25),
    (re.compile(r"ఇరవై\s*ఒకటి"), 21),
    (re.compile(r"ఇరవై\s*రెండు"), 22),
    (re.compile(r"ఇరవై\s*మూడు"), 23),
    (re.compile(r"ఇరవై\s*నాలుగు"), 24),
    (re.compile(r"ఇరవై\s*ఎనిమిది"), 28),
)


def telugu_spoken_day(text: str) -> int | None:
    raw = text or ""
    for pat, day in _TELUGU_SPOKEN_DAY:
        if pat.search(raw):
            return day
    return None


def single_day_in_utterance(text: str) -> int | None:
    spoken = telugu_spoken_day(_without_long_digits(text))
    if spoken is not None:
        return spoken
    t = _normalize_text(_without_long_digits(text))
    guest_n = extract_guest_count(text)
    for om in _ORDINAL_DAY_RE.finditer(t):
        for g in om.groups():
            if g:
                d = int(g)
                if guest_n != d and 1 <= d <= 31:
                    return d
    days = [int(x) for x in _STANDALONE_DAYS.findall(t) if 1 <= int(x) <= 31]
    if guest_n is not None:
        days = [d for d in days if d != guest_n]
    if len(days) == 1:
        return days[0]
    tarikhs = [int(x) for x in _DAY_TARIKH_RE.findall(t)]
    if len(tarikhs) == 1 and not days:
        return tarikhs[0]
    return None


def is_stay_duration_ambiguous(text: str) -> int | None:
    t = (text or "").lower()
    if not re.search(r"డేజి|డేస్|\bdays?\b|రోజుల", t):
        return None
    n = single_day_in_utterance(text)
    if n and 1 <= n <= 31:
        return n
    return None


def _sync_iso_days(state: BookingState) -> None:
    if state.check_in_day:
        iso = _day_to_iso(state.check_in_day)
        if iso:
            state.check_in = iso
    if state.check_out_day:
        iso = _day_to_iso(state.check_out_day)
        if iso:
            state.check_out = iso


def merge_utterance(state: BookingState, text: str) -> BookingState:
    state = apply_corrections(state, text)
    guests = extract_guest_count(text)
    guest_only = guests is not None and re.search(
        r"(వస్తారు|మంది|guests?|members?|గురం|గురు|నలుగురు)", text or "", re.I
    )
    if guest_only and not extract_dates(text) and explicit_check_in_day(text) is None:
        state.guest_count = guests
        state.last_utterance_hash = utterance_fingerprint(text)
        state.updated_at = datetime.now(IST).isoformat()
        return state
    if guests is not None:
        state.guest_count = guests
    t = _normalize_text(text)
    has_month = bool(_MONTH_NAMES.search(t))
    if has_month:
        state.month_confirmed = True

    stay_n = is_stay_duration_ambiguous(text)
    if stay_n is not None:
        state.pending_confirm_field = "duration_vs_checkout"
        state.pending_confirm_day = stay_n
        state.last_utterance_hash = utterance_fingerprint(text)
        state.updated_at = datetime.now(IST).isoformat()
        return state

    cin_explicit = explicit_check_in_day(text)
    cout_explicit = explicit_check_out_day(text)
    if cin_explicit is not None:
        state.check_in_day = cin_explicit
        state.check_in_confirmed = True
        if state.pending_confirm_field in ("duration_vs_checkout",):
            state.pending_confirm_field = None
            state.pending_confirm_day = None
    if cout_explicit is not None:
        state.check_out_day = cout_explicit
        if state.pending_confirm_field in ("duration_vs_checkout",):
            state.pending_confirm_field = None
            state.pending_confirm_day = None

    if cin_explicit is None and cout_explicit is None and not guest_only:
        one = single_day_in_utterance(text)
        if one is not None and not _PAIR_RE.search(t):
            prompt = state.last_prompt or ""
            if (
                is_negation_utterance(text)
                and one is not None
                and state.check_in_day
                and not cout_explicit
                and re.search(r"check[\s\-]?in|చెక్[\s\-]?ఇన్|చెక్\s*ఇన్", t, re.I)
                and not re.search(r"ఔట్|checkout|check out", t, re.I)
            ):
                state.check_in_day = one
                state.check_in_confirmed = True
                if not state.check_out_day:
                    state.check_out = None
                    state.day_only_range = False
                    state.month_confirmed = False
                state.pending_confirm_field = None
                state.pending_confirm_day = None
            elif prompt == "check_out" and state.check_in_confirmed:
                state.check_out_day = one
            elif prompt in ("check_in", "confirm_check_in"):
                state.check_in_day = one
                state.check_in_confirmed = True
            elif not state.check_in_day and booking_intent_utterance(text):
                state.check_in_day = one
                state.check_in_confirmed = True
            elif prompt == "check_out":
                state.check_out_day = one
            elif state.check_in_confirmed and not state.check_out_day:
                state.check_out_day = one
            elif not state.check_in_day:
                state.check_in_day = one
                state.check_in_confirmed = True

    cin, cout = extract_dates(text)
    if _PAIR_RE.search(t):
        if cin:
            state.check_in_day = date.fromisoformat(cin).day
            state.check_in = cin
            state.check_in_confirmed = True
        if cout:
            state.check_out_day = date.fromisoformat(cout).day
            state.check_out = cout
        if not has_month:
            state.day_only_range = True

    bare = _bare_day_numbers(text)
    if (
        state.last_prompt == "month"
        and len(bare) == 1
        and cin_explicit is None
        and cout_explicit is None
        and not _PAIR_RE.search(t)
    ):
        heard_in = bare[0]
        if state.check_in_day != heard_in:
            state.check_in_day = heard_in
            state.check_in_confirmed = True
        state.pending_confirm_field = None
        state.pending_confirm_day = None
        _sync_iso_days(state)
        state.last_utterance_hash = utterance_fingerprint(text)
        state.updated_at = datetime.now(IST).isoformat()
        return state

    phoneish = bool(re.search(r"నంబర|phone|mobile", text or "", re.I)) or (
        len(re.sub(r"\D", "", text or "")) >= 4
    )
    if (
        state.check_out_day
        and len(bare) == 1
        and not phoneish
        and not is_explicit_date_correction(text)
        and cin_explicit is None
        and cout_explicit is None
        and not _PAIR_RE.search(t)
        and state.pending_confirm_field != "duration_vs_checkout"
        and state.last_prompt != "month"
    ):
        heard = bare[0]
        if heard != state.check_out_day:
            state.pending_confirm_field = "check_out"
            state.pending_confirm_day = heard
            state.last_prompt = "confirm_checkout"
            state.last_utterance_hash = utterance_fingerprint(text)
            state.updated_at = datetime.now(IST).isoformat()
            return state

    _sync_iso_days(state)
    if (
        state.check_in_day
        and state.check_out_day
        and not has_month
        and not state.month_confirmed
    ):
        state.day_only_range = True
    if _MONTH_NAMES.search(t) or re.search(r"ఈ\s*నెల|ఈనెల|this month|ఇదే\s*నెల", text or "", re.I):
        state.month_confirmed = True
        state.day_only_range = False
    phone = extract_phone(text)
    if phone:
        state.callback_phone = phone
        state.partial_phone = None
    else:
        frag = _extract_partial_phone(text)
        if frag:
            base = state.partial_phone or ""
            if base and not frag.startswith(base):
                combined = (base + frag)[:10]
            else:
                combined = frag[:10]
            if len(combined) == 10 and combined[0] in "6789":
                state.callback_phone = combined
                state.partial_phone = None
            else:
                state.partial_phone = combined
    state.last_utterance_hash = utterance_fingerprint(text)
    state.updated_at = datetime.now(IST).isoformat()
    return state


def needs_month_clarification(state: BookingState) -> bool:
    has_in = state.check_in_day is not None or state.check_in
    has_out = state.check_out_day is not None or state.check_out
    return bool(state.day_only_range and not state.month_confirmed and has_in and has_out)


def missing_fields(state: BookingState) -> list[str]:
    missing: list[str] = []
    if needs_month_clarification(state):
        missing.append("month")
    if state.check_in_day is None and not state.check_in:
        missing.append("check_in")
    if state.check_out_day is None and not state.check_out:
        missing.append("check_out")
    if not state.guest_count:
        missing.append("guest_count")
    return missing


def booking_recap_kwargs(state: BookingState, lang: str) -> dict[str, str]:
    parts: list[str] = []
    cin_d = state.check_in_day
    cout_d = state.check_out_day
    if cin_d is None and state.check_in:
        cin_d = date.fromisoformat(state.check_in).day
    if cout_d is None and state.check_out:
        cout_d = date.fromisoformat(state.check_out).day
    if lang == "te-IN":
        if cin_d is not None:
            parts.append(f"చెక్-ఇన్ {cin_d}")
        if cout_d is not None:
            parts.append(f"చెక్-అవుట్ {cout_d}")
    elif cin_d is not None and cout_d is not None:
        parts.append(f"check-in {cin_d} to {cout_d}")
    elif cin_d is not None:
        parts.append(f"check-in {cin_d}")
    if state.guest_count:
        parts.append(f"{state.guest_count} మంది")
    need = ""
    if needs_month_clarification(state):
        need = {
            "te-IN": "ఏ నెలలో అనేది చెప్తే చాలు.",
            "hi-IN": "बस महीना बता दीजिए।",
            "en-IN": "Just tell me the month.",
        }.get(lang, "Just tell me the month.")
    return {"summary": ", ".join(parts) if parts else "", "need": need}


def format_date_spoken(iso: str, lang: str) -> str:
    d = date.fromisoformat(iso)
    if lang == "te-IN":
        months_te = (
            "జనవరి",
            "ఫిబ్రవరి",
            "మార్చి",
            "ఏప్రిల్",
            "మే",
            "జూన్",
            "జులై",
            "ఆగస్టు",
            "సెప్టెంబర్",
            "అక్టోబర్",
            "నవంబర్",
            "డిసెంబర్",
        )
        return f"{months_te[d.month - 1]} {d.day}"
    if lang == "hi-IN":
        months_hi = (
            "जनवरी",
            "फ़रवरी",
            "मार्च",
            "अप्रैल",
            "मई",
            "जून",
            "जुलाई",
            "अगस्त",
            "सितंबर",
            "अक्टूबर",
            "नवंबर",
            "दिसंबर",
        )
        return f"{months_hi[d.month - 1]} {d.day}"
    return d.strftime("%B %d")


def booking_state_trace_summary(state: BookingState) -> str:
    """Redacted field names only — for voice_turn logs."""
    bits = []
    if state.check_in_day or state.check_in:
        bits.append(f"check_in_day={state.check_in_day or '?'}")
    if state.check_out_day or state.check_out:
        bits.append(f"check_out_day={state.check_out_day or '?'}")
    if state.guest_count:
        bits.append(f"guests={state.guest_count}")
    if state.pending_confirm_field:
        bits.append(f"confirm={state.pending_confirm_field}")
    if needs_month_clarification(state):
        bits.append("need_month")
    if state.availability_status:
        bits.append(f"avail={state.availability_status}")
    return ",".join(bits) if bits else "empty"


def check_availability(
    state: BookingState,
    *,
    website_knowledge: str | None = None,
) -> BookingState:
    """Stub availability — replace with real PMS hook when wired."""
    if not state.check_in or not state.check_out or not state.guest_count:
        state.availability_status = "pending"
        return state
    web = (website_knowledge or "").lower()
    busy_markers = (
        "sold out",
        "fully booked",
        "no rooms",
        "not available",
        "no availability",
        "booked out",
        "పూర్తిగా బుక్",
        "అవైలబిలిటీ లేదు",
        "గదులు లేవు",
    )
    busy_marker = any(m in web for m in busy_markers)
    large_group = state.guest_count is not None and state.guest_count >= 20
    if large_group and "30" not in web and "large group" not in web:
        busy_marker = False
    state.availability_status = "unavailable" if busy_marker else "available"
    cin = format_date_spoken(state.check_in, "en-IN")
    cout = format_date_spoken(state.check_out, "en-IN")
    state.availability_summary = (
        f"{cin} to {cout}, {state.guest_count} guests — "
        + ("limited rooms; can hold on request." if not busy_marker else "no rooms for those dates.")
    )
    return state


def confirmation_yes(text: str) -> bool | None:
    t = utterance_fingerprint(text)
    raw = text or ""
    yes = {"yes", "ok", "okay", "confirm", "book it", "అవును", "సరే", "బుక్ చేయండి", "हाँ", "हां", "जी", "ठीक है"}
    no = {"no", "cancel", "not now", "వద్దు", "కాదు", "नहीं", "नही"}
    if re.search(
        r"చేశారా|చేసుకున్న|చూశారా|చూసి\s*చెప్|booked yet|did you book|is it booked",
        raw,
        re.I,
    ):
        return None
    if "booked" in t and "book it" not in t:
        return None
    if t in yes or any(
        p in t or p in raw
        for p in ("please book", "go ahead", "book చేయండి", "book చెయ్", "బుక్ చేయండి", "సరిపోతాయి")
    ):
        return True
    if t in no or "cancel" in t:
        return False
    return None
