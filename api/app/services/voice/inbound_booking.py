"""Fast, natural booking turns without LLM when possible."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date

from app.services.voice.booking_state import (
    BOOKING_KEY,
    BookingState,
    booking_recap_kwargs,
    check_availability,
    confirmation_yes,
    dump_booking,
    explicit_check_in_day,
    format_date_spoken,
    is_bare_negation_only,
    is_confusion_prompt,
    is_duplicate_utterance,
    is_incomplete_caller_utterance,
    load_booking,
    merge_utterance,
    missing_fields,
    needs_month_clarification,
)
from app.services.voice.booking_dialogue import (
    business_requires_callback,
    is_book_command,
    is_booking_status_question,
    is_existing_booking_lookup,
    is_phone_declined,
    next_missing_line,
    phone_prompt_for_state,
    recover_already_said,
    reply_booking_status,
    stay_span,
)
from app.services.voice.employee_playbook import (
    booking_intent,
    is_factual_business_question,
    is_pool_timing_question,
    should_run_booking_flow,
    try_grounded_employee_reply,
)

logger = logging.getLogger(__name__)


def _msg(lang: str, key: str, **kwargs: str) -> str:
    bank: dict[str, dict[str, str]] = {
        "incomplete_pause": {
            "te-IN": "సరే, మీరు చెప్పండి — రోజు లేదా తేదీలు పూర్తిగా చెప్పండి.",
            "hi-IN": "जी, आराम से बताइए — तारीख पूरी बता दीजिए।",
            "en-IN": "Sure — take your time. Finish the dates you had in mind.",
        },
        "ask_month": {
            "te-IN": "సరే, {cin_d}న వచ్చి {cout_d}న వెళ్తారు. ఏ నెలలో?",
            "hi-IN": "ठीक है, {cin_d} से {cout_d} तक। किस महीने में?",
            "en-IN": "Got it — check-in {cin_d}, check-out {cout_d}. Which month?",
        },
        "confirm_checkout": {
            "te-IN": "చెక్-అవుట్ {existing}నా? మీరు {heard}నా వినిపించింది — ఏది సరైనది?",
            "hi-IN": "चेक-आउट {existing} है या {heard} सुनाई दिया?",
            "en-IN": "Is check-out on the {existing}, or did you mean the {heard}?",
        },
        "confusion_recap": {
            "te-IN": "{summary} అని చెప్పారు. {need}",
            "hi-IN": "{summary}. {need}",
            "en-IN": "So far: {summary}. {need}",
        },
        "confirm_check_in": {
            "te-IN": "{day}న చెక్-ఇన్ చేయాలనుకుంటున్నారా?",
            "hi-IN": "क्या चेक-इन {day} तारीख को है?",
            "en-IN": "Is check-in on the {day}th?",
        },
        "ask_duration_ambiguous": {
            "te-IN": "{day}వ తేదీన వెళ్తారా, లేక {day} రోజులు ఉండాలనుకుంటున్నారా?",
            "hi-IN": "क्या {day} तारीख को जाएंगे, या {day} दिन रुकना है?",
            "en-IN": "Do you mean checkout on the {day}th, or a {day}-day stay?",
        },
        "ask_check_out_alt": {
            "te-IN": "చెక్-అవుట్ ఏ తేదీకి వెళ్తారు?",
            "hi-IN": "चेक-आउट किस तारीख को होगा?",
            "en-IN": "Which day would you like to check out?",
        },
        "ack_checking": {
            "te-IN": "ఒక్క క్షణం, {cin} నుంచి {cout} వరకు {guests} మందికి స్టే ఉందో చూస్తాను.",
            "hi-IN": "एक पल, {cin} से {cout} तक {guests} लोगों के लिए देखता हूँ।",
            "en-IN": "One moment — checking {cin} to {cout} for {guests} guests.",
        },
        "ask_check_in": {
            "te-IN": "సరే. చెక్-ఇన్ ఏ తేదీకి రావాలి?",
            "hi-IN": "ठीक है। चेक-इन किस तारीख को है?",
            "en-IN": "Sure. What date would you like to check in?",
        },
        "ask_check_out": {
            "te-IN": "సరే. చెక్-ఔట్ ఏ తేదీ?",
            "hi-IN": "चेक-आउट किस तारीख को होगा?",
            "en-IN": "And what date for check-out?",
        },
        "ask_which_date_change": {
            "te-IN": "ఏ తేదీ మార్చాలి?",
            "hi-IN": "कौन-सी तारीख बदलनी है?",
            "en-IN": "Which date should I change?",
        },
        "ask_new_check_in_date": {
            "te-IN": "కొత్త చెక్-ఇన్ తేదీ ఏది?",
            "hi-IN": "नई चेक-इन तारीख क्या होगी?",
            "en-IN": "What is the new check-in date?",
        },
        "ask_guests": {
            "te-IN": "మంచి. ఎంత మంది వస్తారు?",
            "hi-IN": "ठीक है। कितने मेहमान आएंगे?",
            "en-IN": "How many guests will be staying?",
        },
        "ask_phone": {
            "te-IN": "నిర్ధారించడానికి మీ మొబైల్ నంబర్ చెప్పగలరా?",
            "hi-IN": "कन्फ़र्म करने के लिए आपका मोबाइल नंबर बता दीजिए।",
            "en-IN": "To confirm, what mobile number can we reach you on?",
        },
        "available": {
            "te-IN": "{span} {guests} మందికి అవకాశం ఉందండి. బుక్ చేయనా?",
            "hi-IN": "{span} {guests} लोगों के लिए जगह है। बुक कर दूँ?",
            "en-IN": "Open {span} for {guests} guests. Shall I book?",
        },
        "unavailable": {
            "te-IN": "అయ్యో, ఆ తేదీలకు పూర్తిగా ఫుల్ అయిపోయినట్టా. మరో తేదీ చెప్తారా?",
            "hi-IN": "माफ़ कीजिए, उन तारीखों पर फुल लग रहा है। कोई और तारीख बता सकते हैं?",
            "en-IN": "Sorry, those dates look full. Would another date work?",
        },
        "confirmed": {
            "te-IN": "అయిందండి. మీ బుకింగ్ కన్ఫర్మ్ అయింది.",
            "hi-IN": "हो गया। आपकी बुकिंग कन्फ़र्म हो गई।",
            "en-IN": "Done. Your booking is confirmed.",
        },
        "readback": {
            "te-IN": "నోట్ చేసుకున్నాను: {cin} నుంచి {cout}, {guests} మంది. సరైనదేనా?",
            "hi-IN": "नोट किया: {cin} से {cout}, {guests} लोग। सही है?",
            "en-IN": "Got it: {cin} to {cout}, {guests} guests. Is that right?",
        },
    }
    table = bank.get(key, {})
    template = table.get(lang) or table.get("en-IN") or ""
    return template.format(**kwargs)


def _need_line(lang: str, state: BookingState) -> str:
    miss = missing_fields(state)
    if "month" in miss:
        return {
            "te-IN": "నెల ఒక్కటి చెప్తే చాలు.",
            "hi-IN": "बस महीना बता दीजिए।",
            "en-IN": "I just need the month.",
        }.get(lang, "I just need the month.")
    if "guest_count" in miss:
        return _msg(lang, "ask_guests")
    if "check_out" in miss:
        return _msg(lang, "ask_check_out")
    if "check_in" in miss:
        return _msg(lang, "ask_check_in")
    return {
        "te-IN": "ఇంకా ఏదైనా కావాలా?",
        "hi-IN": "और कुछ चाहिए?",
        "en-IN": "Anything else you need?",
    }.get(lang, "")


def try_booking_turn(
    *,
    caller_text: str,
    lang: str,
    fields: dict,
    website_knowledge: str | None,
) -> tuple[str, bool, bool] | None:
    """
    Returns (reply, hangup, used_llm) or None to fall through to generic handler.
    """
    text = (caller_text or "").strip()
    if not text:
        return None

    scoped = dict(fields)
    if website_knowledge:
        scoped["employee_website_knowledge"] = "\n".join(
            part
            for part in (
                str(scoped.get("employee_website_knowledge") or ""),
                website_knowledge,
            )
            if part
        )
    if not should_run_booking_flow(scoped, text):
        return None

    if is_pool_timing_question(text) and not booking_intent(text):
        return None

    state = load_booking(fields)

    if is_factual_business_question(text) and not is_book_command(text):
        grounded = try_grounded_employee_reply(
            text,
            brief=str(fields.get("employee_brief") or ""),
            website_knowledge=website_knowledge,
            lang=lang,
            vertical="lodging",
        )
        if grounded:
            miss = next_missing_line(state, lang) if state.last_prompt else ""
            if miss and state.check_in_day and not state.booking_ref:
                return f"{grounded} {miss}", False, False
            return grounded, False, False

    if is_incomplete_caller_utterance(text):
        return _msg(lang, "incomplete_pause"), False, False

    if is_confusion_prompt(text):
        recap_meta = booking_recap_kwargs(state, lang)
        recap = recap_meta.get("summary", "")
        if not recap:
            return _msg(lang, "ask_check_in"), False, False
        need = recap_meta.get("need") or _need_line(lang, state)
        return (
            _msg(lang, "confusion_recap", summary=recap, need=need),
            False,
            False,
        )

    if is_duplicate_utterance(state, text):
        logger.info("booking duplicate utterance skipped")
        return "", False, False

    if is_bare_negation_only(text):
        fields[BOOKING_KEY] = dump_booking(state)
        if state.last_prompt in ("month", "confirm_check_in", "check_in") or (
            state.check_in_day and state.check_out_day
        ):
            state.last_prompt = "check_in"
            fields[BOOKING_KEY] = dump_booking(state)
            return _msg(lang, "ask_new_check_in_date"), False, False
        return _msg(lang, "ask_which_date_change"), False, False

    prior_pending = state.pending_confirm_field
    state = merge_utterance(state, text)
    fields[BOOKING_KEY] = dump_booking(state)

    if state.pending_confirm_field == "duration_vs_checkout":
        day = str(state.pending_confirm_day or "")
        return _msg(lang, "ask_duration_ambiguous", day=day), False, False

    if state.check_in_day and not state.check_in_confirmed and explicit_check_in_day(text) is None:
        # The caller already named the day. Do not ask them to repeat it.
        state.check_in_confirmed = True
        fields[BOOKING_KEY] = dump_booking(state)

    if is_phone_declined(text):
        state.phone_declined = True

    state = recover_already_said(state, text, fields)
    fields[BOOKING_KEY] = dump_booking(state)

    def _save(reply: str) -> tuple[str, bool, bool]:
        if "చెక్-ఔట్" in reply or "check-out" in reply.lower() or "चेक-आउट" in reply:
            state.last_prompt = "check_out"
        elif "ఎంత మంది" in reply or "How many guests" in reply or "कितने मेहमान" in reply:
            state.last_prompt = "guests"
        elif "ఏ నెల" in reply or "Which month" in reply or "किस महीने" in reply:
            state.last_prompt = "month"
        fields[BOOKING_KEY] = dump_booking(state)
        return reply, False, False

    if state.pending_confirm_field == "check_out" and prior_pending != "check_out":
        existing = (
            format_date_spoken(state.check_out, lang) if state.check_out else ""
        )
        heard = str(state.pending_confirm_day or "")
        return (
            _msg(lang, "confirm_checkout", existing=existing, heard=heard),
            False,
            False,
        )

    if state.pending_confirm_field == "check_out":
        if state.check_out:
            co = date.fromisoformat(state.check_out).day
            heard = state.pending_confirm_day or 0
            if heard and heard == co:
                state.pending_confirm_field = None
                state.pending_confirm_day = None
                fields[BOOKING_KEY] = dump_booking(state)
            elif confirmation_yes(text) is True and state.pending_confirm_day:
                from app.services.voice.booking_state import _day_to_iso

                state.check_out = _day_to_iso(state.pending_confirm_day)
                state.pending_confirm_field = None
                state.pending_confirm_day = None
                fields[BOOKING_KEY] = dump_booking(state)

    def _commit_booking() -> tuple[str, bool, bool]:
        if business_requires_callback(fields, website_knowledge) and not state.phone_declined:
            if not (state.callback_phone and len(state.callback_phone) == 10):
                state.last_prompt = "phone"
                prompt = phone_prompt_for_state(state, lang)
                fields[BOOKING_KEY] = dump_booking(state)
                return prompt or _msg(lang, "ask_phone"), False, False
        if not state.availability_summary and not missing_fields(state):
            checked = check_availability(state, website_knowledge=website_knowledge)
            state.availability_status = checked.availability_status
            state.availability_summary = checked.availability_summary
        if state.availability_status == "unavailable":
            fields[BOOKING_KEY] = dump_booking(state)
            return _msg(lang, "unavailable"), False, False
        if not state.booking_ref:
            ref = f"VF-{uuid.uuid4().hex[:8].upper()}"
            state.booking_ref = ref
            state.booking_confirmed = True
            state.awaiting_confirmation = False
        reply = _msg(lang, "confirmed")
        if state.booking_ref:
            tag = "రిఫరెన్స్" if lang == "te-IN" else "Ref"
            reply = f"{reply} {tag} {state.booking_ref}."
        span = stay_span(state)
        if span and state.check_in and lang == "te-IN":
            reply = f"{reply} {span}."
        fields[BOOKING_KEY] = dump_booking(state)
        return reply, False, False

    if is_booking_status_question(text) or is_existing_booking_lookup(text):
        if not missing_fields(state) and not state.availability_summary and not state.booking_ref:
            state.lookup_in_progress = True
            checked = check_availability(state, website_knowledge=website_knowledge)
            state.availability_status = checked.availability_status
            state.availability_summary = checked.availability_summary
            state.lookup_in_progress = False
            if state.availability_status == "available":
                state.awaiting_confirmation = True
        status = reply_booking_status(
            state,
            lang,
            existing_booking_question=is_existing_booking_lookup(text),
        )
        return _save(status or "ఇంకా బుక్ కాలేదండి.")

    ready = not missing_fields(state)
    affirm = confirmation_yes(text)
    dates_only = "సరిపోతాయి" in text and "guest_count" in missing_fields(state)
    if (is_book_command(text) or (affirm is True and ready and not dates_only)) and (
        state.booking_ref or ready or state.awaiting_confirmation
    ):
        if not ready and not state.booking_ref:
            return _save(f"ఇంకా బుక్ కాలేదండి. {next_missing_line(state, lang)}".strip())
        return _commit_booking()

    if state.phone_declined and state.booking_ref:
        return _save(_msg(lang, "confirmed") + f" రిఫరెన్స్ {state.booking_ref}.")

    if (
        state.partial_phone
        and not state.callback_phone
        and not state.phone_declined
        and (business_requires_callback(fields, website_knowledge) or state.last_prompt == "phone" or re.search(r"\d{4,}", text or ""))
    ):
        # A partial number is kept. Ask only for the missing digits.
        if not (ready and is_book_command(text)):
            prompt = phone_prompt_for_state(state, lang)
            if prompt and (state.last_prompt == "phone" or business_requires_callback(fields, website_knowledge) or re.search(r"\d{6,}", text or "")):
                state.last_prompt = "phone"
                fields[BOOKING_KEY] = dump_booking(state)
                return prompt, False, False

    missing = missing_fields(state)
    if missing:
        if "month" in missing and state.check_in_day and state.check_out_day:
            state.last_prompt = "month"
            fields[BOOKING_KEY] = dump_booking(state)
            return (
                _msg(
                    lang,
                    "ask_month",
                    cin_d=str(state.check_in_day),
                    cout_d=str(state.check_out_day),
                ),
                False,
                False,
            )
        if "check_in" in missing:
            state.last_prompt = "check_in"
            fields[BOOKING_KEY] = dump_booking(state)
            return _msg(lang, "ask_check_in"), False, False
        if "check_out" in missing:
            repeat = state.last_prompt == "check_out"
            line = (
                _msg(lang, "ask_check_out")
                if repeat or not state.check_in_day
                else f"సరే, {state.check_in_day}న చెక్-ఇన్. చెక్-ఔట్ ఏ తేదీ?"
            )
            if lang != "te-IN":
                line = next_missing_line(state, lang)
            state.last_prompt = "check_out"
            fields[BOOKING_KEY] = dump_booking(state)
            return line, False, False
        if "guest_count" in missing:
            state.last_prompt = "guests"
            fields[BOOKING_KEY] = dump_booking(state)
            return _msg(lang, "ask_guests"), False, False

    if not missing and not state.availability_summary:
        state = check_availability(state, website_knowledge=website_knowledge)
        guests = str(state.guest_count or "")
        logger.info(
            "booking availability status=%s guests=%s",
            state.availability_status,
            guests,
        )
        if state.availability_status == "unavailable":
            fields[BOOKING_KEY] = dump_booking(state)
            return _msg(lang, "unavailable"), False, False
        state.awaiting_confirmation = True
        state.lookup_in_progress = False
        state.month_confirmed = state.month_confirmed or not needs_month_clarification(state)
        fields[BOOKING_KEY] = dump_booking(state)
        return _msg(lang, "available", span=stay_span(state), guests=guests), False, False

    if state.booking_ref:
        from app.services.voice.employee_playbook import is_post_booking_side_question

        if is_post_booking_side_question(text):
            return None
        if is_booking_status_question(text):
            status = reply_booking_status(state, lang)
            if status:
                return _save(status)
        if confirmation_yes(text) is True and not is_book_command(text):
            ack = {
                "te-IN": "సరే అండి. ఇంకా ఏ సహాయం కావాలా?",
                "hi-IN": "ठीक है जी, और कुछ चाहिए?",
                "en-IN": "Sure. Anything else I can help with?",
            }.get(lang, "Anything else?")
            return ack, False, False
        return None

    if not missing and state.availability_summary and not state.awaiting_confirmation:
        return (
            _msg(
                lang,
                "readback",
                cin=format_date_spoken(state.check_in or "", lang),
                cout=format_date_spoken(state.check_out or "", lang),
                guests=str(state.guest_count or ""),
            ),
            False,
            False,
        )

    if state.partial_phone and not state.callback_phone and not state.phone_declined:
        prompt = phone_prompt_for_state(state, lang)
        if prompt:
            return prompt, False, False

    if state.awaiting_confirmation:
        return "సరే అండి. బుక్ చేయనా?" if lang == "te-IN" else "Shall I book that?", False, False

    return None