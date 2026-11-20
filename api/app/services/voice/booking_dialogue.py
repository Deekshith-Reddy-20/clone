"""Booking status questions and partial phone — resort/lodging calls."""

from __future__ import annotations

import re

from app.services.voice.booking_state import BookingState, missing_fields


_STATUS_RE = re.compile(
    r"(?:book|బుక్|बुक|बुकिंग).{0,28}(?:చేశారా|చేసుకున్నావా|చేసుకున్నారా|చేసావా|చేశావా|చేశారు|అయిందా|किया|हुई|yet|done\b)"
    r"|బుక్\s*చేశారా|బుక్\s*చేసారా|బుక్\s*చేసుకున్నావా|బుక్\s*అయిందా"
    r"|చూశారా|చూశావా|చూసి\s*చెప్"
    r"|did you book|booked yet|is it booked|booking done|have you booked",
    re.I,
)


def is_booking_status_question(text: str) -> bool:
    """Did you book / did you check — including the Roman word book."""
    te = text or ""
    low = te.lower()
    if _STATUS_RE.search(te) or _STATUS_RE.search(low):
        return True
    return any(
        p in te or p in low
        for p in (
            "కన్ఫర్మ్ అయిందా",
            "confirmed?",
            "is it confirmed",
        )
    )


def is_existing_booking_lookup(text: str) -> bool:
    """Caller asks if they already have a reservation (not room availability)."""
    low = (text or "").lower()
    te = text or ""
    if "already" in low and "book" in low:
        return True
    if re.search(r"(booking|బుక్|బుకింగ్).{0,24}ఉందా", te, re.I):
        return True
    if "ఉందా" in te and re.search(r"\bbook", low) and "నాకు" in te:
        return True
    return any(p in te for p in ("నాకు బుకింగ్", "నా బుకింగ్", "ముందే బుక్"))


def is_book_command(text: str) -> bool:
    """Caller is telling us to book now, not asking whether it is booked."""
    if is_booking_status_question(text):
        return False
    te = text or ""
    low = te.lower()
    if "బుక్కేరా" in te:
        return True
    if "మూసుకొని" in te and re.search(r"book|బుక్", te, re.I):
        return True
    if re.search(
        r"(?:book|బుక్|बुक)\s*(?:చెయ్|చేయ|చేయండి|करो|कर दो|it\b|please)",
        te,
        re.I,
    ):
        return True
    return "please book" in low or "go ahead and book" in low


def is_phone_declined(text: str) -> bool:
    te = text or ""
    low = te.lower()
    return any(
        p in te or p in low
        for p in (
            "అవసరం లేదు",
            "నంబర్ వద్దు",
            "నెంబర్ వద్దు",
            "మొబైల్ వద్దు",
            "no number",
            "no phone",
            "don't need",
            "number not needed",
            "phone not needed",
        )
    )


def business_requires_callback(fields: dict | None, website_knowledge: str | None = None) -> bool:
    raw = (fields or {}).get("employee_requires_callback")
    if raw in (True, "true", "yes", "1", 1):
        return True
    blob = " ".join(
        [
            str((fields or {}).get("employee_brief") or ""),
            str((fields or {}).get("employee_website_knowledge") or ""),
            str(website_knowledge or ""),
        ]
    ).lower()
    return any(
        p in blob
        for p in ("callback required", "mobile number required", "phone required")
    )


def caller_claims_already_said(text: str) -> bool:
    te = text or ""
    low = te.lower()
    return "చెప్పా" in te or "ఇందాక" in te or "already told" in low or "i told you" in low


_TE_DIGITS = {1: "ఒక్క", 2: "రెండు", 3: "మూడు", 4: "నాలుగు", 5: "ఐదు", 6: "ఆరు"}


def extract_partial_phone(text: str) -> str | None:
    """4–9 digit mobile fragment (incomplete number)."""
    t = re.sub(r"\D", "", text or "")
    if len(t) == 10 and t[0] in "6789":
        return None
    m = re.search(r"([6-9]\d{3,8})$", t)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{4,9})\b", re.sub(r"[^\d\s]", " ", text or ""))
    if m:
        frag = m.group(1)
        if 4 <= len(frag) <= 9 and frag[0] in "6789":
            return frag
    return None


def recover_already_said(state: BookingState, text: str, fields: dict | None) -> BookingState:
    """'I already told you' — pull the fact from this call before asking again."""
    if not caller_claims_already_said(text):
        return state
    from app.services.voice.booking_state import extract_guest_count, extract_phone

    chunks = [text or ""]
    chat = (fields or {}).get("inbound_chat")
    if isinstance(chat, dict):
        for turn in chat.get("turns") or []:
            if turn.get("role") == "user" and turn.get("text"):
                chunks.append(str(turn["text"]))
    blob = "\n".join(chunks)
    if not state.guest_count:
        guests = extract_guest_count(blob)
        if guests:
            state.guest_count = guests
    if not state.callback_phone:
        phone = extract_phone(blob)
        if phone:
            state.callback_phone = phone
            state.partial_phone = None
        elif not state.partial_phone:
            frag = extract_partial_phone(blob)
            if frag:
                state.partial_phone = frag
    return state


def merge_partial_phone(state: BookingState, text: str) -> BookingState:
    from app.services.voice.booking_state import extract_phone

    full = extract_phone(text)
    if full:
        state.callback_phone = full
        state.partial_phone = None
        return state
    frag = extract_partial_phone(text)
    if not frag:
        return state
    if state.callback_phone and frag in state.callback_phone:
        return state
    if state.partial_phone and not state.callback_phone:
        combined = (state.partial_phone + frag)[:10]
        if len(combined) == 10 and combined[0] in "6789":
            state.callback_phone = combined
            state.partial_phone = None
        else:
            state.partial_phone = combined
    else:
        state.partial_phone = frag
    return state


def phone_prompt_for_state(state: BookingState, lang: str) -> str | None:
    if state.callback_phone and len(state.callback_phone) == 10:
        return None
    partial = (state.partial_phone or "").strip()
    if partial:
        need = max(0, 10 - len(partial))
        te_need = _TE_DIGITS.get(need, str(need))
        return {
            "te-IN": f"{partial} వినిపించింది. ఇంకో {te_need} అంకెలు చెప్పండి.",
            "hi-IN": f"{partial} सुनाई दिया। बाकी {need} अंक बता दीजिए।",
            "en-IN": f"I heard {partial}. What are the remaining {need} digits?",
        }.get(lang, "Please finish the mobile number.")
    return {
        "te-IN": "నిర్ధారించడానికి మీ మొబైల్ నంబర్ చెప్పగలరా అండి?",
        "hi-IN": "कन्फ़र्म करने के लिए मोबाइल नंबर बता दीजिए।",
        "en-IN": "What mobile number can we reach you on?",
    }.get(lang, "Mobile number please?")


def stay_span(state: BookingState) -> str:
    cin = state.check_in_day
    cout = state.check_out_day
    if cin is None and state.check_in:
        from datetime import date

        cin = date.fromisoformat(state.check_in).day
    if cout is None and state.check_out:
        from datetime import date

        cout = date.fromisoformat(state.check_out).day
    if cin and cout:
        return f"{cin} నుంచి {cout} వరకు"
    return ""


def next_missing_line(state: BookingState, lang: str) -> str:
    miss = missing_fields(state)
    if "month" in miss and state.check_in_day and state.check_out_day:
        return {
            "te-IN": f"సరే, {state.check_in_day}న వచ్చి {state.check_out_day}న వెళ్తారు. ఏ నెలలో?",
            "hi-IN": f"ठीक है, {state.check_in_day} से {state.check_out_day} तक। किस महीने में?",
            "en-IN": f"Got it — {state.check_in_day} to {state.check_out_day}. Which month?",
        }.get(lang, "Which month?")
    if "check_out" in miss:
        if state.last_prompt == "check_out":
            return {
                "te-IN": "సరే. చెక్-ఔట్ ఏ తేదీ?",
                "hi-IN": "चेक-आउट किस तारीख को होगा?",
                "en-IN": "And what date for check-out?",
            }.get(lang, "What is check-out?")
        if state.check_in_day:
            return {
                "te-IN": f"సరే, {state.check_in_day}న చెక్-ఇన్. చెక్-ఔట్ ఏ తేదీ?",
                "hi-IN": f"चेक-इन {state.check_in_day}। चेक-आउट किस तारीख को?",
                "en-IN": f"Check-in on the {state.check_in_day}. What is check-out?",
            }.get(lang, "What is check-out?")
        return {
            "te-IN": "సరే. చెక్-ఔట్ ఏ తేదీ?",
            "hi-IN": "चेक-आउट किस तारीख को होगा?",
            "en-IN": "And what date for check-out?",
        }.get(lang, "What is check-out?")
    if "guest_count" in miss:
        return {
            "te-IN": "ఎంత మంది వస్తారు?",
            "hi-IN": "कितने मेहमान आएंगे?",
            "en-IN": "How many guests?",
        }.get(lang, "How many guests?")
    if "check_in" in miss:
        return {
            "te-IN": "సరే. చెక్-ఇన్ ఏ తేదీకి రావాలి?",
            "hi-IN": "चेक-इन किस तारीख को है?",
            "en-IN": "What date would you like to check in?",
        }.get(lang, "What is check-in?")
    return ""


def not_booked_line(lang: str) -> str:
    return {
        "te-IN": "ఇంకా బుక్ కాలేదండి.",
        "hi-IN": "अभी बुक नहीं हुई।",
        "en-IN": "Not booked yet.",
    }.get(lang, "Not booked yet.")


def reply_booking_status(
    state: BookingState,
    lang: str,
    *,
    existing_booking_question: bool = False,
) -> str | None:
    if state.booking_ref or getattr(state, "booking_confirmed", False):
        ref = state.booking_ref or ""
        base = {
            "te-IN": "అయిందండి. మీ బుకింగ్ కన్ఫర్మ్ అయింది.",
            "hi-IN": "हाँ जी, आपकी बुकिंग कन्फ़र्म हो गई है।",
            "en-IN": "Yes — your booking is confirmed.",
        }.get(lang, "Your booking is confirmed.")
        extra = ""
        if ref:
            extra = f" రిఫరెన్స్ {ref}." if lang == "te-IN" else f" Ref {ref}."
        span = stay_span(state) if state.check_in else ""
        if lang == "te-IN" and span and state.guest_count:
            return f"{base}{extra} {span} {state.guest_count} మంది."
        if extra:
            return f"{base}{extra}"
        return base

    if getattr(state, "lookup_in_progress", False) and not state.availability_summary:
        return {
            "te-IN": "ఇంకా బుక్ కాలేదండి. ఆ తేదీల్లో ఖాళీ ఉందో చూస్తున్నాను.",
            "hi-IN": "अभी बुक नहीं हुई। उन तारीखों के लिए उपलब्धता देख रहा हूँ।",
            "en-IN": "Not booked yet. I am still checking those dates.",
        }.get(lang, "Still checking availability.")

    if (
        state.availability_status == "available"
        and state.availability_summary
        and state.guest_count
        and not missing_fields(state)
    ):
        span = stay_span(state)
        guests = str(state.guest_count)
        return {
            "te-IN": f"ఇంకా బుక్ కాలేదండి. {span} {guests} మందికి అవకాశం ఉందండి. బుక్ చేయనా?",
            "hi-IN": f"अभी बुक नहीं हुई। {span} {guests} लोगों के लिए जगह है। बुक कर दूँ?",
            "en-IN": f"Not booked yet. Open {span} for {guests} guests. Shall I book?",
        }.get(lang, "Not booked yet. Shall I book?")

    lead = not_booked_line(lang)
    nxt = next_missing_line(state, lang)
    if existing_booking_question or nxt:
        return f"{lead} {nxt}".strip() if nxt else lead
    return lead