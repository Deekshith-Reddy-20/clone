"""Deterministic lodging booking slots for LLM-first calls."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from app.services.voice.booking_dialogue import is_book_command
from app.services.voice.booking_state import (
    BOOKING_KEY,
    BookingState,
    confirmation_yes,
    dump_booking,
    extract_guest_count,
    load_booking,
    merge_utterance,
    utterance_fingerprint,
)
from app.services.voice.voice_dates import apply_resolved_dates_to_booking, resolve_dates, today_local

_WEEKDAY_EN_FULL = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_TE_WEEKDAY_FULL = (
    "సోమవారం",
    "మంగళవారం",
    "బుధవారం",
    "గురువారం",
    "శుక్రవారం",
    "శనివారం",
    "ఆదివారం",
)
_PEOPLE_RE = re.compile(
    r"(వస్తారు|మంది|guests?|members?|గురం|గురు|నలుగురు|people)",
    re.I,
)
_NIGHTS_ASK = re.compile(r"(ఎన్ని\s*nights|how many nights)", re.I)
_GUESTS_ASK = re.compile(r"(ఎంత\s*మంది|how many guests)", re.I)
_CONFIRM_ASK = re.compile(r"(పెట్టమంటారా|confirm|ఇలా\s*request)", re.I)
_DATE_ASK = re.compile(r"(check-?in|చెక్-ఇన్|తేదీ)", re.I)
_INTERRUPT_RE = re.compile(
    r"(pool|పూల్|swim|price|rate|ధర|ఎంత|ఉందా\?|amenit|jacuzzi|spa\b|timing|సమయం)",
    re.I,
)

_ACK_GUEST_FNS = (
    lambda n: f"సరే అండి, {n} guests note చేశాను.",
    lambda n: f"ok అండి, {n} guests.",
    lambda n: f"అలాగే, {n} మంది noted.",
    lambda n: f"noted — {n} guests.",
)

# Spoken night counts when the agent just asked "ఎన్ని nights?"
_TE_NIGHT_WORDS = (
    (re.compile(r"ఒక్క|ఒకటి|\bone\b|\ba\s+night\b", re.I), 1),
    (re.compile(r"రెండు|\btwo\b", re.I), 2),
    (re.compile(r"మూడు|\bthree\b", re.I), 3),
    (re.compile(r"నాలుగు|\bfour\b", re.I), 4),
    (re.compile(r"ఐదు|అయిదు|\bfive\b", re.I), 5),
    (re.compile(r"ఆరు|\bsix\b", re.I), 6),
    (re.compile(r"ఏడు|\bseven\b", re.I), 7),
    (re.compile(r"ఎనిమిది|\beight\b", re.I), 8),
    (re.compile(r"తొమ్మిది|\bnine\b", re.I), 9),
    (re.compile(r"పది|\bten\b", re.I), 10),
)
_BARE_NIGHTS_RE = re.compile(
    r"(?:^|[^\d])([1-9]|1[0-4])(?:\s*(?:nights?|రాత్రులు|నైట్|అండి|only|రోజులు))?\.?\s*$",
    re.I,
)


def _iso_or_none(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def nights_count(state: BookingState) -> int | None:
    if state.nights:
        return state.nights
    cin, cout = _iso_or_none(state.check_in), _iso_or_none(state.check_out)
    if cin and cout and cout > cin:
        return (cout - cin).days
    return None


def extract_nights_answer(text: str) -> int | None:
    """Parse nights from a short answer to 'how many nights?'."""
    raw = (text or "").strip()
    if not raw:
        return None
    resolved = resolve_dates(raw, anchor=today_local())
    if resolved.nights and 1 <= resolved.nights <= 14:
        return resolved.nights
    for pat, n in _TE_NIGHT_WORDS:
        if pat.search(raw):
            return n
    m = _BARE_NIGHTS_RE.search(raw)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 14:
            return n
    # Digits-only STT crumbs: "2", "02"
    if re.fullmatch(r"0?[1-9]|1[0-4]", raw):
        return int(raw)
    return None


def sync_checkout_from_nights(state: BookingState) -> BookingState:
    """Derive check-out from check-in + nights (caller need not say checkout)."""
    n = nights_count(state)
    cin = _iso_or_none(state.check_in)
    if not n or not cin:
        return state
    state.nights = n
    state.check_out = (cin + timedelta(days=n)).isoformat()
    state.check_out_day = (cin + timedelta(days=n)).day
    return state


def spoken_stay_date(d: date, *, lang: str, anchor: date | None = None) -> str:
    anchor = anchor or today_local()
    if lang == "te-IN":
        wd = _TE_WEEKDAY_FULL[d.weekday()]
        base = f"{wd} {d.day} {d.strftime('%B')}"
    else:
        wd = _WEEKDAY_EN_FULL[d.weekday()]
        base = f"{wd} {d.day} {d.strftime('%B')}"
    if d.year != anchor.year:
        return f"{base} {d.year}"
    return base


def format_check_in_label(state: BookingState, *, lang: str = "te-IN") -> str:
    d = _iso_or_none(state.check_in)
    if not d:
        return "MISSING"
    return spoken_stay_date(d, lang=lang)


def _phone_line(state: BookingState, fields: dict) -> str:
    if state.callback_phone:
        return state.callback_phone[-4:] + " (callback)"
    e164 = str(fields.get("caller_e164") or "").strip()
    if e164:
        return f"{e164} (caller ID)"
    return "MISSING"


def slot_status(state: BookingState) -> str:
    if state.booking_confirmed:
        return "submitted"
    if state.awaiting_confirmation:
        return "awaiting_confirm"
    return "collecting"


def missing_booking_slots(state: BookingState, fields: dict) -> list[str]:
    """Slots required before we ask for verbal confirmation.

    Phone is collected after confirm (Exotel usually already has From=). Requiring
    phone here blocked confirmation and made the agent re-ask పెట్టమంటారా forever.
    """
    miss: list[str] = []
    if not state.check_in:
        miss.append("check_in")
    if not nights_count(state):
        miss.append("nights")
    if not state.guest_count:
        miss.append("guests")
    return miss


def next_missing_slot(state: BookingState, fields: dict) -> str | None:
    miss = missing_booking_slots(state, fields)
    return miss[0] if miss else None


def infer_last_slot_asked(last_agent: str, state: BookingState) -> str | None:
    if state.last_slot_asked:
        return state.last_slot_asked
    t = last_agent or ""
    if _CONFIRM_ASK.search(t):
        return "confirm"
    if _NIGHTS_ASK.search(t):
        return "nights"
    if _GUESTS_ASK.search(t):
        return "guests"
    if _DATE_ASK.search(t) and "check-out" not in t.lower():
        return "check_in"
    if state.last_prompt in ("check_in", "check_out", "guests", "month", "confirm_checkout"):
        if state.last_prompt == "guests":
            return "guests"
        if state.last_prompt in ("check_out", "confirm_checkout"):
            return "nights"
        return state.last_prompt
    return None


def is_people_count_utterance(text: str) -> bool:
    guests = extract_guest_count(text)
    return guests is not None and bool(_PEOPLE_RE.search(text or ""))


def pick_ack(fields: dict, *, kind: str, guest_n: int | None = None) -> str:
    key = f"slot_ack_{kind}"
    idx = int(fields.get(key) or 0)
    fields[key] = (idx + 1) % len(_ACK_GUEST_FNS)
    if kind == "guests" and guest_n:
        return _ACK_GUEST_FNS[idx](guest_n)
    return _ACK_GUEST_FNS[idx](guest_n or 0)


def is_booking_interrupt(caller_text: str) -> bool:
    from app.services.voice.employee_playbook import is_factual_business_question

    t = caller_text or ""
    if is_factual_business_question(t):
        return True
    if _INTERRUPT_RE.search(t):
        return True
    if re.search(r"\b(what|how|ఏంటి|ఎప్పుడు|ఎంత)\b", t, re.I) and not resolve_dates(
        t, anchor=today_local()
    ).check_in:
        if not is_people_count_utterance(t) and not resolve_dates(t, anchor=today_local()).nights:
            if len(t.split()) > 2:
                return True
    return False


def apply_slot_merge(
    fields: dict,
    caller_text: str,
    *,
    last_agent_reply: str | None = None,
) -> dict:
    state = load_booking(fields)
    last_slot = infer_last_slot_asked(last_agent_reply or "", state)
    text = caller_text or ""

    nights_ans = (
        extract_nights_answer(text)
        if last_slot == "nights" and not is_people_count_utterance(text)
        else None
    )

    if last_slot == "nights" and is_people_count_utterance(text):
        g = extract_guest_count(text)
        if g:
            state.guest_count = g
            state.last_utterance_hash = utterance_fingerprint(text)
            fields[BOOKING_KEY] = dump_booking(state)
            fields = apply_resolved_dates_to_booking(fields, "", anchor=today_local())
            state = load_booking(fields)
            fields["_slot_guest_from_nights_question"] = True
    elif last_slot == "nights" and nights_ans:
        # Bare "2" / "రెండు" must not be treated as a calendar day.
        state.nights = nights_ans
        state.last_utterance_hash = utterance_fingerprint(text)
        state = sync_checkout_from_nights(state)
        fields[BOOKING_KEY] = dump_booking(state)
    else:
        state = merge_utterance(state, text)
        fields[BOOKING_KEY] = dump_booking(state)
        fields = apply_resolved_dates_to_booking(fields, text, anchor=today_local())
        state = load_booking(fields)

    resolved = resolve_dates(text, anchor=today_local())
    if not nights_ans and resolved.nights and last_slot != "guests":
        nights_ans = resolved.nights

    if nights_ans and 1 <= nights_ans <= 14:
        state.nights = nights_ans
        state = sync_checkout_from_nights(state)

    if slot_verbal_reject(text) and (nights_ans or resolved.nights):
        n = nights_ans or resolved.nights
        if n:
            state.nights = n
            state = sync_checkout_from_nights(state)
        state.awaiting_confirmation = False
        fields["_slot_reject_reread"] = True

    # Keep checkout aligned whenever nights + check-in are known.
    state = sync_checkout_from_nights(state)
    fields[BOOKING_KEY] = dump_booking(state)
    return fields


def format_booking_slot_block(state: BookingState, fields: dict) -> str:
    n = nights_count(state)
    nights_s = str(n) if n else "MISSING"
    guests_s = str(state.guest_count) if state.guest_count else "MISSING"
    nxt = next_missing_slot(state, fields) or "confirm"
    if slot_status(state) == "awaiting_confirm":
        nxt = "confirm"
    elif slot_status(state) == "submitted":
        nxt = "done"
    cin = format_check_in_label(state, lang=str(fields.get("conversation_language") or "te-IN"))
    return (
        "BOOKING: "
        f"check_in={cin} | nights={nights_s} | guests={guests_s} | "
        f"room=any | phone={_phone_line(state, fields)} | "
        f"status={slot_status(state)}. NEXT: {nxt}."
    )


def ask_line_for_slot(slot: str, lang: str, _state: BookingState) -> str:
    if slot == "check_in":
        return {
            "te-IN": "check-in తేదీ చెప్పండి అండి.",
            "en-IN": "What date would you like to check in?",
        }.get(lang, "Check-in date?")
    if slot == "nights":
        return {
            "te-IN": "ఎన్ని nights అండి?",
            "en-IN": "How many nights?",
        }.get(lang, "How many nights?")
    if slot == "guests":
        return {
            "te-IN": "ఎంత మంది వస్తారు?",
            "en-IN": "How many guests?",
        }.get(lang, "How many guests?")
    if slot == "phone":
        return {
            "te-IN": "confirm కోసం మీ మొబైల్ నంబర్ చెప్పగలరా?",
            "en-IN": "What mobile number can we reach you on?",
        }.get(lang, "Mobile number?")
    return ""


def short_progress_ack(filled: list[str], state: BookingState, lang: str) -> str:
    """Ack only what the caller just gave — never invent an unrelated note."""
    if "nights" in filled and state.nights:
        return {
            "te-IN": f"సరే అండి, {state.nights} nights.",
            "hi-IN": f"ठीक है, {state.nights} nights.",
            "en-IN": f"Got it — {state.nights} nights.",
        }.get(lang, f"Got it — {state.nights} nights.")
    if "guests" in filled and state.guest_count:
        return {
            "te-IN": f"సరే అండి, {state.guest_count} guests.",
            "hi-IN": f"ठीक है, {state.guest_count} guests.",
            "en-IN": f"Got it — {state.guest_count} guests.",
        }.get(lang, f"Got it — {state.guest_count} guests.")
    if "check_in" in filled and state.check_in:
        when = format_check_in_label(state, lang=lang)
        return {
            "te-IN": f"సరే అండి, {when} check-in.",
            "hi-IN": f"ठीक है, {when} check-in.",
            "en-IN": f"Got it — {when} check-in.",
        }.get(lang, f"Got it — {when} check-in.")
    return {
        "te-IN": "సరే అండి.",
        "hi-IN": "ठीक है जी.",
        "en-IN": "Got it.",
    }.get(lang, "Got it.")


def collapse_repeated_spoken(text: str) -> str:
    """Drop stuttered words and back-to-back duplicate sentences."""
    t = (text or "").strip()
    if not t:
        return t
    # Immediate word doubles: "సరే సరే" / "check-in check-in"
    t = re.sub(r"(\S+)(?:\s+\1)+", r"\1", t, flags=re.I)
    # Duplicate consecutive sentences
    parts = re.split(r"(?<=[.!?।?])\s+", t)
    out: list[str] = []
    prev = ""
    for p in parts:
        norm = re.sub(r"\s+", " ", p.strip().lower())
        if norm and norm != prev:
            out.append(p.strip())
            prev = norm
    return " ".join(out).strip() or t


def confirmation_readback(state: BookingState, lang: str) -> str:
    d = _iso_or_none(state.check_in)
    if not d:
        return ask_line_for_slot("check_in", lang, state)
    n = nights_count(state) or 0
    g = state.guest_count or 0
    when = spoken_stay_date(d, lang=lang)
    if lang == "te-IN":
        return f"{when} check-in, {n} nights, {g} guests — ఇలా request పెట్టమంటారా?"
    return f"{when} check-in, {n} nights, {g} guests — shall I note this request?"


def outcome_after_booking(state: BookingState, lang: str) -> str:
    d = _iso_or_none(state.check_in)
    n = nights_count(state) or 0
    g = state.guest_count or 0
    when = spoken_stay_date(d, lang=lang) if d else "తేదీ"
    if lang == "te-IN":
        return (
            f"Request note చేశాను అండి — {when}, {n} nights, {g} guests. "
            "Availability confirm చేసి మా team మీకు call చేస్తారు."
        )
    return (
        f"I've noted your request — {when}, {n} nights, {g} guests. "
        "Our team will confirm availability and call you back."
    )


def slots_ready(state: BookingState, fields: dict) -> bool:
    return not missing_booking_slots(state, fields)


def set_slot_asked(state: BookingState, slot: str) -> BookingState:
    state.last_slot_asked = slot
    state.last_prompt = {
        "check_in": "check_in",
        "nights": "check_out",
        "guests": "guests",
        "confirm": "confirm_checkout",
        "phone": "guests",
    }.get(slot, slot)
    return state


def slot_verbal_yes(text: str, *, awaiting_confirm: bool) -> bool:
    if confirmation_yes(text) is True:
        return True
    if not awaiting_confirm:
        return False
    raw = (text or "").strip()
    low = raw.lower().strip(".,!? ")
    # Telugu phone acks are often a single syllable after the confirm question.
    if raw in {"ఆ", "హా", "అవును", "సరే"} or low in {"ok", "okay", "yes", "sure", "haan", "ha"}:
        return True
    return any(
        p in raw or p in low
        for p in (
            "అవును",
            "అవునండి",
            "ఇలాగే",
            "ఆ అండి",
            "పెట్టండి",
            "పెట్టు",
            "పెట్టేయండి",
            "yes",
            "confirm",
            "సరే confirm",
            "okay అండి",
            "ok అండి",
            "note చేయండి",
        )
    )


def slot_verbal_reject(text: str) -> bool:
    if confirmation_yes(text) is False:
        return True
    raw = text or ""
    if any(w in raw for w in ("వద్దు", "కాదు", "change", "మార్చు", "లేదు")):
        if resolve_dates(raw, anchor=today_local()).nights or re.search(r"nights?|నైట్", raw, re.I):
            return True
    return False


def llm_booking_turn_suffix(state: BookingState, fields: dict, lang: str) -> str:
    nxt = next_missing_slot(state, fields) or "confirm"
    if state.booking_confirmed:
        return (
            "[BOOKING_MODE: Request already noted. Do NOT re-read the note. "
            "Short soft follow-up only (ఇంకా ఏ సహాయం కావాలా?). Never hang up / goodbye unless they say bye.]"
        )
    if state.awaiting_confirmation:
        return (
            "[BOOKING_MODE: Answer any FACTS question in one short sentence. "
            "If they confirm, say you are noting the request — do NOT read back dates yourself. "
            "If they change nights/dates, acknowledge briefly only. "
            "Do not call create_booking. Do not end the call.]"
        )
    return (
        f"[BOOKING_MODE: Answer caller question from FACTS only — never say మాకు X ఉంది unless FACTS list X. "
        f"Then one short ack (noted / అలాగే అండి / ok అండి — vary, no repeat). "
        f"Ask exactly ONE slot: {nxt}. "
        f"Never ask check-out date — checkout is computed from check-in + nights. "
        f"No బుక్ చేస్తాం / check-in చేస్తాం before confirmation. "
        f"Full weekday (ఆదివారం) + day + month. No create_booking. Do not end the call.]"
    )


def append_missing_slot_if_needed(reply: str, fields: dict, lang: str) -> str:
    st = load_booking(fields)
    if st.awaiting_confirmation or st.booking_confirmed:
        return reply
    miss = next_missing_slot(st, fields)
    if not miss:
        return reply
    ask = ask_line_for_slot(miss, lang, st)
    if not ask:
        return reply
    low = (reply or "").lower()
    if miss == "nights" and "night" in low:
        return reply
    if miss == "guests" and ("guest" in low or "మంది" in reply or "వస్తారు" in reply):
        return reply
    if miss == "check_in" and ("check-in" in low or "తేదీ" in reply):
        return reply
    return f"{(reply or '').strip()} {ask}".strip()


def lodging_booking_call(fields: dict) -> bool:
    from app.services.voice.inbound_vertical import inbound_vertical

    if inbound_vertical(fields) == "lodging":
        return True
    brief = str(fields.get("employee_brief") or "").lower()
    if any(k in brief for k in ("resort", "hotel", "farm stay", "v farms")):
        return True
    prof = fields.get("employee_business_profile")
    if isinstance(prof, dict):
        blob = json.dumps(prof, ensure_ascii=False).lower()
        if "resort" in blob or "lodging" in blob:
            return True
    return False


def lodging_slot_collecting(fields: dict, caller_text: str) -> bool:
    from app.services.voice.booking_state import booking_intent_utterance
    from app.services.voice.employee_playbook import booking_flow_active

    st = load_booking(fields)
    if st.booking_confirmed:
        return False
    if booking_flow_active(fields) or st.last_slot_asked:
        return True
    return booking_intent_utterance(caller_text) or bool(st.check_in)


def handle_booking_slot_turn(
    db,
    call,
    fields: dict,
    caller_text: str,
    lang: str,
    last_agent_reply: str | None,
    execute_tool_fn,
    *,
    miss_before: list[str] | None = None,
) -> tuple[str | None, dict, bool]:
    """Code-rendered replies: read-back, re-read-back after correction, outcome only.

    Third return value is hangup (only for explicit end_call / bye paths upstream).
    Noting an enquiry does not hang up — call stays open for follow-ups.
    """
    if not lodging_booking_call(fields):
        return None, fields, False

    if miss_before is None:
        miss_before = missing_booking_slots(load_booking(fields), fields)
    state = load_booking(fields)
    text = caller_text or ""
    interrupt = is_booking_interrupt(text)

    if fields.pop("_slot_reject_reread", None):
        state.awaiting_confirmation = True
        state = set_slot_asked(state, "confirm")
        fields[BOOKING_KEY] = dump_booking(state)
        return confirmation_readback(state, lang), fields, False

    if state.booking_confirmed:
        # Stay on the line after enquiry is noted. Soft acks must NOT replay the note
        # (lodging_slot_collecting is False once confirmed — handle soft here first).
        if slot_verbal_yes(text, awaiting_confirm=True) or len((text or "").strip()) <= 12:
            soft = {
                "te-IN": "సరే అండి. ఇంకా ఏ సహాయం కావాలా?",
                "hi-IN": "ठीक है जी, और कुछ चाहिए?",
                "en-IN": "Sure. Anything else I can help with?",
            }.get(lang, "Anything else?")
            return soft, fields, False
        return outcome_after_booking(state, lang), fields, False

    if not lodging_slot_collecting(fields, caller_text):
        return None, fields, False

    if state.awaiting_confirmation:
        if slot_verbal_reject(text):
            state = set_slot_asked(state, "confirm")
            fields[BOOKING_KEY] = dump_booking(state)
            return confirmation_readback(state, lang), fields, False
        if slot_verbal_yes(text, awaiting_confirm=True):
            if "create_booking" not in [str(x.get("name")) for x in (fields.get("tool_log") or [])]:
                _, fields, _ = execute_tool_fn(
                    "create_booking",
                    {"confirmed_verbal": True},
                    tool_source="slot_flow",
                )
                state = load_booking(fields)
                state = sync_checkout_from_nights(state)
                state.booking_confirmed = True
                state.awaiting_confirmation = False
                fields[BOOKING_KEY] = dump_booking(state)
            return outcome_after_booking(load_booking(fields), lang), fields, False
        if interrupt:
            return None, fields, False
        # Do not re-ask the same confirm line for unclear crumbs — nudge once.
        if len((text or "").strip()) <= 4:
            nudge = {
                "te-IN": "సరే అండి — request పెట్టమంటారా, లేదా మార్పు ఉందా?",
                "hi-IN": "कन्फर्म करूँ, या कुछ बदलना है?",
                "en-IN": "Shall I note this request, or change something?",
            }.get(lang, "Confirm the request, or change something?")
            return nudge, fields, False
        if not slots_ready(state, fields):
            miss = next_missing_slot(state, fields)
            ask = ask_line_for_slot(miss or "guests", lang, state)
            if ask:
                state = set_slot_asked(state, miss or "guests")
                state.awaiting_confirmation = False
                fields[BOOKING_KEY] = dump_booking(state)
                return ask, fields, False
        state = set_slot_asked(state, "confirm")
        fields[BOOKING_KEY] = dump_booking(state)
        return confirmation_readback(state, lang), fields, False

    miss_after = missing_booking_slots(state, fields)
    filled = [s for s in miss_before if s not in miss_after]
    just_filled = len(miss_before) > 0 and len(miss_after) == 0
    if just_filled and not interrupt:
        state.awaiting_confirmation = True
        state = set_slot_asked(state, "confirm")
        fields[BOOKING_KEY] = dump_booking(state)
        return confirmation_readback(state, lang), fields, False

    # Own the slot turns: ack what they said, ask only the next missing slot.
    # Stops LLM from inventing checkout asks / fake "noted your number" / re-asks.
    if not interrupt and miss_after:
        nxt = next_missing_slot(state, fields) or miss_after[0]
        ask = ask_line_for_slot(nxt, lang, state)
        if filled:
            ack = short_progress_ack(filled, state, lang)
            state = set_slot_asked(state, nxt)
            fields[BOOKING_KEY] = dump_booking(state)
            return collapse_repeated_spoken(f"{ack} {ask}".strip()), fields, False
        if ask:
            state = set_slot_asked(state, nxt)
            fields[BOOKING_KEY] = dump_booking(state)
            # Unclear crumb — short re-ask only, do not paraphrase the whole last turn.
            if len((text or "").strip()) <= 16 or slot_verbal_yes(text, awaiting_confirm=False):
                soft_ask = {
                    "te-IN": f"సరే అండి — {ask}",
                    "hi-IN": f"ठीक है — {ask}",
                    "en-IN": f"Sure — {ask}",
                }.get(lang, ask)
                return collapse_repeated_spoken(soft_ask), fields, False
            return collapse_repeated_spoken(ask), fields, False

    return None, fields, False


def infer_capture_slot(text: str, state: BookingState, last_agent: str | None) -> str | None:
    last = infer_last_slot_asked(last_agent or "", state)
    if last == "nights" and is_people_count_utterance(text):
        return "guests"
    if last == "nights" and extract_nights_answer(text):
        return "nights"
    if resolve_dates(text, anchor=today_local()).check_in:
        return "check_in"
    if resolve_dates(text, anchor=today_local()).nights or extract_nights_answer(text):
        return "nights"
    if is_people_count_utterance(text):
        return "guests"
    return None