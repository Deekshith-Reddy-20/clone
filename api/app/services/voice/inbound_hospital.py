"""Deterministic hospital OP turns — no lodging check-in/checkout."""

from __future__ import annotations

import logging
import re
import uuid

from app.services.employee_knowledge import combine_supplemental_knowledge
from app.services.voice.appointment_state import (
    APPOINTMENT_KEY,
    AppointmentState,
    dump_appointment,
    load_appointment,
    merge_appointment_utterance,
    missing_appointment_fields,
)
from app.services.voice.employee_playbook import try_knowledge_snippet_reply
from app.services.voice.spoken_output import emergency_reply, is_emergency_utterance

logger = logging.getLogger(__name__)


def hospital_appointment_intent(text: str) -> bool:
    low = (text or "").lower()
    te = text or ""
    markers = (
        "appointment",
        "apointment",
        "opd",
        "doctor",
        "department",
        "see a doctor",
        "consult",
        "clinic",
        "అపాయింట్",
        "డాక్టర్",
        "ఓపీ",
        "వైద్యుడు",
        "కలవ",
        "अपॉइंटमेंट",
        "डॉक्टर",
        "डॉक्टर",
    )
    if any(m in low or m in te for m in markers):
        return True
    if "apartment" in low and "book" in low:
        return True
    if re.search(r"\bbook\b", low) and any(k in low for k in ("doctor", "opd", "clinic")):
        return True
    return False


def lodging_misroute_complaint(text: str) -> bool:
    te = text or ""
    low = (text or "").lower()
    return (
        "checkout" in low
        or "check-out" in low
        or "check out" in low
        or "చెక్-ఔట్" in te
        or "హోటల్" in te
        or ("check" in low and "hotel" in low)
    )


def appointment_status_question(text: str) -> bool:
    te = text or ""
    low = (text or "").lower()
    return any(
        p in te or p in low
        for p in (
            "చూశారా",
            "బుక్ చేశారా",
            "confirm",
            "confirmed",
            "booked",
            "book చేశారా",
            "book చేసుకున్నావా",
            "కన్ఫర్మ్",
            "status",
        )
    )


def should_run_hospital_flow(fields: dict, caller_text: str) -> bool:
    st = load_appointment(fields)
    if any(
        (
            st.department,
            st.preferred_date,
            st.callback_phone,
            st.awaiting_confirmation,
            st.lookup_status,
            st.last_prompt,
        )
    ):
        return True
    return hospital_appointment_intent(caller_text)


def _location_reply(
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
) -> str | None:
    snippet = try_knowledge_snippet_reply(
        "హాస్పిటల్ ఎక్కడ ఉంది location address",
        brief=brief,
        website_knowledge=website_knowledge,
        lang=lang,
    )
    if snippet and not snippet.startswith("You"):
        return f"మా హాస్పిటల్ హైదరాబాద్‌లో ఉందండి. {snippet[:90]}".strip()
    corpus = combine_supplemental_knowledge(brief, website_knowledge or "")
    for line in corpus.split("\n"):
        if any(k in line.lower() for k in ("hyderabad", "gachibowli", "address", "location", "లోకేషన్")):
            return f"మా హాస్పిటల్ హైదరాబాద్‌లో ఉందండి. {line.strip()[:100]}"
    if lang == "te-IN":
        return "మా హాస్పిటల్ హైదరాబాద్‌లో ఉందండి."
    return "Our hospital is in Hyderabad."


def _msg(lang: str, key: str, **kwargs: str) -> str:
    bank: dict[str, dict[str, str]] = {
        "ask_appointment_clarify": {
            "te-IN": "డాక్టర్ అపాయింట్‌మెంట్ గురించే కదా అండి?",
        },
        "start_appointment": {
            "te-IN": "సరే అండి, డాక్టర్‌ని కలవడానికి అపాయింట్‌మెంట్ చూద్దాం. మీకు ఏ రోజు వీలవుతుంది?",
            "hi-IN": "ठीक है जी। डॉक्टर से मिलने का अपॉइंटमेंट देखते हैं। कौन-सी तारीख ठीक रहेगी?",
        },
        "checkout_apology": {
            "te-IN": "క్షమించండి అండి, నేను తప్పుగా అడిగాను. ఓపీ అపాయింట్‌మెంట్‌కి మీరు వచ్చే తేదీ, టైమ్ చాలు.",
        },
        "ask_department": {
            "te-IN": "ఏ డాక్టర్ లేదా డిపార్ట్‌మెంట్ కావాలో చెప్పండి అండి.",
            "hi-IN": "कौन-से डॉक्टर या डिपार्टमेंट के लिए अपॉइंटमेंट चाहिए?",
        },
        "ask_date": {
            "te-IN": "అపాయింట్‌మెంట్‌కి ఏ తేదీ వీలవుతుంది అండి?",
            "hi-IN": "अपॉइंटमेंट के लिए कौन-सी तारीख ठीक रहेगी?",
        },
        "ask_phone": {
            "te-IN": "ఒక్క సారి మీ మొబైల్ నంబర్ చెప్పగలరా అండి?",
            "hi-IN": "मोबाइल नंबर बता दीजिए।",
        },
        "phone_already": {
            "te-IN": "అవునండి, మీరు చెప్పిన నంబర్ నా దగ్గర ఉంది.",
        },
        "lookup_pending": {
            "te-IN": "ఇంకా కన్ఫర్మ్ కాలేదండి. ఒక్కసారి చూస్తాను.",
            "hi-IN": "अभी कन्फ़र्म नहीं हुआ। एक बार देखता हूँ।",
        },
        "lookup_done_unconfirmed": {
            "te-IN": "ఇంకా కన్ఫర్మ్ కాలేదండి. స్లాట్ చూస్తున్నాను.",
            "hi-IN": "अभी कन्फ़र्म नहीं हुआ। स्लॉट देख रहा हूँ।",
        },
        "booked": {
            "te-IN": "అపాయింట్‌మెంట్ నోట్ చేశానండి. రిఫరెన్స్ {ref}.",
            "hi-IN": "अपॉइंटमेंट नोट कर लिया। रेफरेंस {ref}।",
        },
        "book_unavailable": {
            "te-IN": "ఇక్కడి నుంచి అపాయింట్‌మెంట్ కన్ఫర్మ్ చేయలేకపోతున్నానండి.",
        },
    }
    template = (bank.get(key) or {}).get(lang) or (bank.get(key) or {}).get("te-IN", "")
    return template.format(**kwargs)


def try_hospital_turn(
    *,
    caller_text: str,
    lang: str,
    fields: dict,
    brief: str,
    website_knowledge: str | None,
    vertical: str,
) -> tuple[str, bool, bool] | None:
    """Returns (reply, hangup, used_llm) or None."""
    text = (caller_text or "").strip()
    if not text or vertical != "hospital":
        return None

    if is_emergency_utterance(text):
        return emergency_reply(lang), False, False

    if lodging_misroute_complaint(text):
        st = load_appointment(fields)
        st.last_prompt = "date"
        fields[APPOINTMENT_KEY] = dump_appointment(st)
        return _msg(lang, "checkout_apology"), False, False

    low = text.lower()
    if "apartment" in low and "book" in low and not hospital_appointment_intent(text):
        return _msg(lang, "ask_appointment_clarify"), False, False

    if any(k in low or k in text for k in ("ఎక్కడ", "location", "address", "లోకేషన్", "హాస్పిటల్")):
        loc = _location_reply(brief=brief, website_knowledge=website_knowledge, lang=lang)
        if loc:
            st = load_appointment(fields)
            merge_appointment_utterance(st, text)
            fields[APPOINTMENT_KEY] = dump_appointment(st)
            return loc, False, False

    state = load_appointment(fields)

    if hospital_appointment_intent(text) and not state.preferred_date and not state.department:
        low = text.lower()
        if "doctor" in low or "డాక్టర్" in text or "see" in low or "opd" in low:
            state.last_prompt = "date"
            fields[APPOINTMENT_KEY] = dump_appointment(state)
            return _msg(lang, "start_appointment"), False, False

    if not should_run_hospital_flow(fields, text):
        return None

    if state.callback_phone and any(
        k in text for k in ("నంబర్", "నంబరు", "number", "mobile", "phone")
    ):
        if any(k in text for k in ("మళ్ళీ", "again", "repeat", "చెప్పాలా", "చెప్ప")):
            return _msg(lang, "phone_already"), False, False

    if appointment_status_question(text):
        if state.booking_confirmed and state.booking_ref:
            return _msg(lang, "booked", ref=state.booking_ref), False, False
        if state.lookup_status == "pending" or state.awaiting_confirmation:
            return _msg(lang, "lookup_pending"), False, False
        return _msg(lang, "lookup_done_unconfirmed"), False, False

    state = merge_appointment_utterance(state, text)
    fields[APPOINTMENT_KEY] = dump_appointment(state)

    if state.callback_phone and state.last_prompt == "phone":
        return _msg(lang, "phone_already"), False, False

    miss = missing_appointment_fields(state)
    if miss:
        if "department" in miss:
            state.last_prompt = "department"
            fields[APPOINTMENT_KEY] = dump_appointment(state)
            return _msg(lang, "ask_department"), False, False
        if "date" in miss:
            state.last_prompt = "date"
            fields[APPOINTMENT_KEY] = dump_appointment(state)
            return _msg(lang, "ask_date"), False, False
        if "phone" in miss:
            if state.callback_phone:
                pass
            else:
                state.last_prompt = "phone"
                fields[APPOINTMENT_KEY] = dump_appointment(state)
                return _msg(lang, "ask_phone"), False, False

    if not state.lookup_status:
        state.lookup_status = "pending"
        state.awaiting_confirmation = True
        fields[APPOINTMENT_KEY] = dump_appointment(state)
        return _msg(lang, "lookup_pending"), False, False

    if state.awaiting_confirmation and re.search(r"\b(yes|ok|okay|అవును|సరే|confirm)\b", low + text):
        ref = state.booking_ref or f"OP-{uuid.uuid4().hex[:8].upper()}"
        state.booking_ref = ref
        state.booking_confirmed = True
        state.awaiting_confirmation = False
        state.lookup_status = "booked"
        fields[APPOINTMENT_KEY] = dump_appointment(state)
        return _msg(lang, "booked", ref=ref), False, False

    return _msg(lang, "lookup_pending"), False, False