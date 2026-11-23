from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Call
from app.models.enums import CallOutcome
from app.services.employee_knowledge import refresh_call_grounding
from app.services.telephony.inbound_mode import use_sarvam_inbound_voice
from app.services.voice.booking_state import (
    BOOKING_KEY,
    booking_state_trace_summary,
    dump_booking,
    is_incomplete_caller_utterance,
    load_booking,
)
from app.services.voice.gemini import generate_agent_reply as generate_agent_reply_gemini
from app.services.voice.employee_playbook import (
    booking_flow_active,
    booking_intent,
    is_pool_timing_question,
    should_prefer_reception_llm,
    try_grounded_employee_reply,
    office_attendant_prompt,
    try_knowledge_gap_reply,
    try_knowledge_missing_reply,
    try_knowledge_snippet_reply,
    try_personal_boundary_reply,
    try_pool_timing_reply,
)
from app.services.voice.inbound_booking import try_booking_turn
from app.services.voice.inbound_hospital import try_hospital_turn
from app.services.voice.inbound_llm_engine import llm_first_enabled
from app.services.voice.inbound_vertical import inbound_vertical
from app.services.voice.voice_leads import (
    callback_promise_reply,
    is_callback_confirm_offer,
    is_human_transfer_request,
    save_lead_intent,
    transfer_reply,
    try_value_offer_snippet,
)
from app.services.voice.spoken_output import filter_caller_facing_reply, is_emergency_utterance, emergency_reply
from app.services.voice.sarvam import generate_agent_reply as generate_agent_reply_sarvam
from app.services.voice.sarvam import (
    avoid_repeat_reply,
    is_clarify_fallback,
    is_spurious_stt_snippet,
    language_bcp47_from_employee,
    resolve_call_language,
    resolve_conversation_language,
    sanitize_reply_for_lang,
)

logger = logging.getLogger(__name__)

MAX_TURNS = 14


def _employee_prefers_telugu(fields: dict) -> bool:
    raw = str(fields.get("employee_language") or "")
    return language_bcp47_from_employee(raw) == "te-IN"


_SHORT_ACK = frozenset(
    {
        "ha",
        "hmm",
        "hm",
        "yes",
        "ok",
        "okay",
        "yeah",
        "yep",
        "hello",
        "hi",
        "హా",
        "అవును",
        "సరే",
        "हाँ",
        "हां",
        "जी",
    }
)


def _chat_state(call: Call) -> dict:
    fields = call.captured_fields or {}
    chat = fields.get("inbound_chat")
    if not isinstance(chat, dict):
        chat = {"turns": []}
    if "turns" not in chat:
        chat["turns"] = []
    return chat


def _brief_for_call(call: Call) -> str:
    fields = call.captured_fields or {}
    brief = fields.get("employee_brief")
    if isinstance(brief, str) and brief.strip():
        return brief.strip()
    return "You are a helpful Karyuk phone agent."


def _website_knowledge_for_call(call: Call) -> str | None:
    fields = call.captured_fields or {}
    web = fields.get("employee_website_knowledge")
    if isinstance(web, str) and web.strip():
        return web.strip()
    return None


def _website_url_for_call(call: Call) -> str | None:
    fields = call.captured_fields or {}
    url = fields.get("employee_website_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def _natural_spoken_for_call(call: Call) -> bool:
    fields = call.captured_fields or {}
    if "employee_natural_spoken" in fields:
        return bool(fields.get("employee_natural_spoken"))
    return True


def _appointment_context_for_llm(fields: dict) -> str:
    from app.services.voice.appointment_state import load_appointment

    st = load_appointment(fields)
    parts: list[str] = []
    if st.department:
        parts.append(f"dept={st.department}")
    if st.preferred_date:
        parts.append(f"date={st.preferred_date}")
    if st.callback_phone:
        parts.append("phone=captured")
    if st.booking_ref:
        parts.append(f"ref={st.booking_ref}")
    return "; ".join(parts)


def _booking_context_for_llm(fields: dict) -> str:
    st = load_booking(fields)
    parts = []
    if st.check_in:
        parts.append(f"check_in={st.check_in}")
    if st.check_out:
        parts.append(f"check_out={st.check_out}")
    if st.guest_count:
        parts.append(f"guests={st.guest_count}")
    if st.callback_phone:
        parts.append("phone=captured")
    if st.availability_status:
        parts.append(f"availability={st.availability_status}")
    return "; ".join(parts)


def _last_agent_line(turns: list[dict[str, str]]) -> str | None:
    for t in reversed(turns):
        if t.get("role") == "assistant" and (t.get("text") or "").strip():
            return str(t["text"])
    return None


def _finalize_reply(
    reply: str,
    turns: list[dict[str, str]],
    lang: str,
    *,
    fields: dict | None = None,
    vertical: str = "general",
) -> str:
    reply = filter_caller_facing_reply((reply or "").strip(), lang=lang)
    reply = sanitize_reply_for_lang(reply, lang, vertical=vertical)
    if not reply:
        return reply
    from app.services.voice.appointment_state import load_appointment

    st = load_booking(fields)
    appt = load_appointment(fields or {})
    booking_active = bool(
        st.check_in_day
        or st.check_out_day
        or st.check_in
        or st.guest_count
        or st.last_prompt
        or appt.department
        or appt.preferred_date
        or appt.callback_phone
        or appt.last_prompt
    )
    if llm_first_enabled():
        return reply
    return avoid_repeat_reply(
        reply,
        _last_agent_line(turns),
        booking_active=booking_active,
    )


def process_inbound_speech(
    db: Session,
    call: Call,
    *,
    caller_text: str,
    stt_language: str | None = None,
) -> tuple[str, bool]:
    """Returns (agent_reply, should_hangup). Empty reply = skip TTS (duplicate event)."""
    from app.services.voice.inbound_llm_engine import llm_first_enabled, process_inbound_speech_llm_first

    if llm_first_enabled():
        chat = _chat_state(call)
        turns: list[dict[str, str]] = list(chat.get("turns") or [])
        return process_inbound_speech_llm_first(
            db,
            call,
            caller_text=caller_text,
            stt_language=stt_language,
            turns=turns,
            append_fn=_append_and_save,
        )

    text = (caller_text or "").strip()
    chat = _chat_state(call)
    turns: list[dict[str, str]] = list(chat.get("turns") or [])

    fields = refresh_call_grounding(db, call)
    emp_lang = fields.get("employee_language")
    conv_lang = fields.get("conversation_language")
    vertical = inbound_vertical(fields)
    brief = _brief_for_call(call)
    web_know = _website_knowledge_for_call(call)

    if is_emergency_utterance(text):
        bcp47 = resolve_call_language(
            caller_text=text,
            conversation_language=conv_lang,
            employee_language=emp_lang,
            stt_language=stt_language,
        )
        reply = _finalize_reply(emergency_reply(bcp47), turns, bcp47, fields=fields, vertical=vertical)
        fields["conversation_language"] = bcp47
        call.captured_fields = fields
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return reply, False

    if not text:
        if use_sarvam_inbound_voice():
            lang = resolve_call_language(
                caller_text="",
                conversation_language=conv_lang,
                employee_language=emp_lang,
                stt_language=stt_language,
            )
            retries = {
                "te-IN": "క్షమించండి, నాకు వినిపించలేదు. మళ్ళీ చెప్పగలరా?",
                "hi-IN": "माफ़ कीजिए, मुझे सुनाई नहीं दिया। क्या आप दोबारा बता सकते हैं?",
                "en-IN": "Sorry, I did not catch that. Could you repeat?",
            }
            return retries.get(lang, retries["en-IN"]), False
        return "Sorry, I did not catch that. Could you repeat?", False

    if is_spurious_stt_snippet(text):
        lang = resolve_call_language(
            caller_text=text,
            conversation_language=conv_lang,
            employee_language=emp_lang,
            stt_language=stt_language,
        )
        retries = {
            "te-IN": "క్షమించండి, స్పష్టంగా వినిపించలేదు. మళ్ళీ చెప్పండి.",
            "hi-IN": "माफ़ कीजिए, मुझे साफ़ सुनाई नहीं दिया। कृपया दोबारा बताइए।",
            "en-IN": "Sorry, I did not catch that clearly. Please say that again.",
        }
        reply = _finalize_reply(
            retries.get(lang, retries["en-IN"]), turns, lang, fields=fields, vertical=vertical
        )
        fields["conversation_language"] = lang
        call.captured_fields = fields
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return reply, False

    bcp47 = resolve_call_language(
        caller_text=text,
        conversation_language=conv_lang,
        employee_language=emp_lang,
        stt_language=stt_language,
    )
    fields["conversation_language"] = bcp47
    call.captured_fields = fields

    lowered = text.lower()
    hangup_phrases = (
        "goodbye",
        "bye bye",
        "that's all",
        "thank you bye",
        "hang up",
        "alvida",
        "వీడ్కోలు",
        "అంతే చాలు",
        "anthe chalu",
    )
    # Clear goodbye only — short thanks / acks after a noted request must not hang up.
    if any(p in lowered for p in hangup_phrases) or "అంతే చాలు" in text:
        bye = {
            "te-IN": "సరే అండి, థ్యాంక్యూ.",
            "hi-IN": "ठीक है जी, धन्यवाद।",
            "en-IN": "Sure, thank you.",
        }
        reply = bye.get(bcp47, bye["en-IN"])
        _append_and_save(db, call, turns, text, reply, hangup=True)
        return reply, True

    from app.services.voice.m05_sarvam import generate_m05_reply, m05_voice_enabled

    if m05_voice_enabled(call_fields=fields):
        history = [{"role": t["role"], "text": t["text"]} for t in turns[-8:]]
        reply = generate_m05_reply(
            caller_text=text,
            history=history,
            reply_language=bcp47,
            employee_language=str(emp_lang or ""),
        )
        if reply:
            fields["speech_stack"] = "sarvam-m05"
            fields["conversation_language"] = bcp47
            call.captured_fields = fields
            hangup = "goodbye" in reply.lower() and len(turns) > 2
            _append_and_save(db, call, turns, text, reply, hangup=hangup)
            return reply, hangup

    if is_incomplete_caller_utterance(text):
        if vertical == "hospital":
            reply = {
                "te-IN": "సరే అండి, మీరు చెప్పేది పూర్తి వినిపించలేదు. మళ్ళీ చెప్పండి.",
                "hi-IN": "जी, आराम से पूरी बात बताइए।",
                "en-IN": "Sure — please finish what you were saying.",
            }.get(bcp47, "Please continue.")
        else:
            reply = {
                "te-IN": "సరే అండి, మీరు చెప్పేది పూర్తి వినిపించలేదు. మళ్ళీ చెప్పండి.",
                "hi-IN": "जी, आराम से पूरी बात बताइए।",
                "en-IN": "Sure — please finish what you were saying.",
            }.get(bcp47, "Please continue.")
        reply = _finalize_reply(reply, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return reply, False

    from app.services.voice.employee_playbook import try_compliment_reply

    compliment = try_compliment_reply(text, bcp47)
    if compliment:
        compliment = _finalize_reply(compliment, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, compliment, hangup=False)
        return compliment, False

    if is_human_transfer_request(text):
        fields = save_lead_intent(fields, reason="transfer", caller_text=text)
        fields["voice_transfer_requested"] = True
        call.captured_fields = fields
        reply = _finalize_reply(
            transfer_reply(bcp47), turns, bcp47, fields=fields, vertical=vertical
        )
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return reply, False

    value = try_value_offer_snippet(
        text, website_knowledge=web_know, brief=brief, lang=bcp47
    )
    if value:
        value = _finalize_reply(value, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, value, hangup=False)
        return value, False

    personal_reply = try_personal_boundary_reply(text, bcp47)
    if personal_reply:
        personal_reply = _finalize_reply(
            personal_reply, turns, bcp47, fields=fields, vertical=vertical
        )
        _append_and_save(db, call, turns, text, personal_reply, hangup=False)
        return personal_reply, False

    hospital_result = try_hospital_turn(
        caller_text=text,
        lang=bcp47,
        fields=fields,
        brief=brief,
        website_knowledge=web_know,
        vertical=vertical,
    )
    if hospital_result is not None:
        reply, hangup, _ = hospital_result
        call.captured_fields = {**(call.captured_fields or {}), **fields}
        if reply == "":
            db.commit()
            return "", False
        reply = _finalize_reply(reply, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, reply, hangup=hangup)
        return reply, hangup

    if is_pool_timing_question(text) and not booking_intent(text):
        pool = try_pool_timing_reply(
            text,
            website_knowledge=web_know,
            brief=brief,
            lang=bcp47,
        )
        if pool:
            pool = _finalize_reply(pool, turns, bcp47, fields=fields, vertical=vertical)
            _append_and_save(db, call, turns, text, pool, hangup=False)
            return pool, False

    grounded = try_grounded_employee_reply(
        text,
        brief=brief,
        website_knowledge=web_know,
        lang=bcp47,
        vertical=vertical,
        fields=fields,
    )
    if is_callback_confirm_offer(text) or re.search(
        r"(confirm|తెలియదు|not sure|unsure).{0,40}(call|కాల్)", text or "", re.I
    ):
        fields = save_lead_intent(fields, reason="confirm_facts", caller_text=text)
        call.captured_fields = fields
        cb = _finalize_reply(
            callback_promise_reply(bcp47), turns, bcp47, fields=fields, vertical=vertical
        )
        _append_and_save(db, call, turns, text, cb, hangup=False)
        return cb, False

    if grounded:
        st_mid = load_booking(fields)
        if booking_flow_active(fields) and st_mid.last_prompt and not st_mid.booking_ref:
            from app.services.voice.booking_dialogue import next_missing_line

            miss = next_missing_line(st_mid, bcp47)
            if miss and miss not in grounded:
                grounded = f"{grounded} {miss}"
        grounded = _finalize_reply(grounded, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, grounded, hangup=False)
        return grounded, False

    if not booking_flow_active(fields) and not booking_intent(text):
        gap = try_knowledge_gap_reply(
            text, brief=brief, website_knowledge=web_know, lang=bcp47
        )
        if gap:
            gap = _finalize_reply(gap, turns, bcp47, fields=fields, vertical=vertical)
            _append_and_save(db, call, turns, text, gap, hangup=False)
            return gap, False

    if should_prefer_reception_llm(text, fields) and use_sarvam_inbound_voice():
        history = [{"role": t["role"], "text": t["text"]} for t in turns[-8:]]
        ctx_bits = [_booking_context_for_llm(fields), _appointment_context_for_llm(fields)]
        ctx = " ".join(b for b in ctx_bits if b)
        caller_for_llm = text if not ctx else f"{text}\n[call_state: {ctx}]"
        llm_reply = generate_agent_reply_sarvam(
            employee_brief=brief,
            caller_text=caller_for_llm,
            history=history,
            reply_language=bcp47,
            website_knowledge=web_know,
            website_url=_website_url_for_call(call),
            natural_spoken=_natural_spoken_for_call(call),
            vertical=vertical,
        )
        if llm_reply and llm_reply.strip() and not is_clarify_fallback(
            llm_reply, bcp47, vertical=vertical
        ):
            fields["speech_stack"] = "sarvam"
            reply = _finalize_reply(llm_reply, turns, bcp47, fields=fields, vertical=vertical)
            _append_and_save(db, call, turns, text, reply, hangup=False)
            return reply, False

    booking_result = try_booking_turn(
        caller_text=text,
        lang=bcp47,
        fields=fields,
        website_knowledge=web_know,
    )
    call.captured_fields = {**fields, BOOKING_KEY: fields.get(BOOKING_KEY)}
    if booking_result is not None:
        reply, hangup, _ = booking_result
        if reply == "":
            db.commit()
            return "", False
        reply = _finalize_reply(reply, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, reply, hangup=hangup)
        return reply, hangup

    if is_pool_timing_question(text):
        pool = try_pool_timing_reply(
            text,
            website_knowledge=web_know,
            brief=brief,
            lang=bcp47,
        )
        if pool:
            pool = _finalize_reply(pool, turns, bcp47, fields=fields, vertical=vertical)
            _append_and_save(db, call, turns, text, pool, hangup=False)
            return pool, False

    norm = text.strip().lower().replace(".", "")
    if norm in _SHORT_ACK or (len(norm) <= 3 and norm.isalpha()):
        if vertical == "hospital":
            reply = {
                "te-IN": "చెప్పండి అండి, ఎలా సహాయం చేయగలను?",
                "hi-IN": "बताइए, मैं कैसे मदद करूँ?",
                "en-IN": "How can I help?",
            }.get(bcp47, "How can I help?")
        elif booking_flow_active(fields):
            reply = {
                "te-IN": "సరే. చెక్-ఇన్ ఏ తేదీకి రావాలి?",
                "hi-IN": "ठीक है। चेक-इन किस तारीख को है?",
                "en-IN": "Sure. What date would you like to check in?",
            }.get(bcp47, "What date would you like to check in?")
        else:
            reply = office_attendant_prompt(
                bcp47, brief=brief, website_knowledge=web_know
            )
        reply = _finalize_reply(reply, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return reply, False

    if len(turns) >= MAX_TURNS * 2:
        from app.services.voice.voice_repair_policy import frustration_closing, llm_closing_instruction

        reply = frustration_closing(lang=bcp47, fields=fields)
        _append_and_save(db, call, turns, text, reply, hangup=True)
        return reply, True

    missing = try_knowledge_missing_reply(
        text, website_knowledge=web_know, brief=brief, lang=bcp47
    )
    if missing:
        reply = _finalize_reply(missing, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return reply, False
    from app.services.voice.employee_playbook import try_brand_knowledge_reply

    brand = try_brand_knowledge_reply(
        text,
        brief=brief,
        website_knowledge=web_know,
        lang=bcp47,
    )
    if brand:
        brand = _finalize_reply(brand, turns, bcp47, fields=fields, vertical=vertical)
        _append_and_save(db, call, turns, text, brand, hangup=False)
        return brand, False

    snippet = try_knowledge_snippet_reply(
        text,
        brief=brief,
        website_knowledge=web_know,
        lang=bcp47,
    )
    if snippet:
        _append_and_save(db, call, turns, text, snippet, hangup=False)
        return snippet, False

    history = [{"role": t["role"], "text": t["text"]} for t in turns[-6:]]
    booking_ctx = _booking_context_for_llm(fields)
    caller_for_llm = text if not booking_ctx else f"{text}\n[booking_state: {booking_ctx}]"

    if use_sarvam_inbound_voice():
        reply = generate_agent_reply_sarvam(
            employee_brief=brief,
            caller_text=caller_for_llm,
            history=history,
            reply_language=bcp47,
            website_knowledge=web_know,
            website_url=_website_url_for_call(call),
            natural_spoken=_natural_spoken_for_call(call),
            vertical=vertical,
        )
    else:
        reply = generate_agent_reply_gemini(employee_brief=brief, caller_text=text, history=history)
    if is_clarify_fallback(reply, bcp47, vertical=vertical) or not (reply or "").strip():
        reply = (
            try_grounded_employee_reply(
                text,
                brief=brief,
                website_knowledge=web_know,
                lang=bcp47,
                vertical=vertical,
                fields=fields,
            )
            or try_knowledge_snippet_reply(
                text, brief=brief, website_knowledge=web_know, lang=bcp47
            )
            or office_attendant_prompt(bcp47, brief=brief, website_knowledge=web_know)
        )
    fields["speech_stack"] = "sarvam"
    hangup = "goodbye" in reply.lower() and len(turns) > 2
    reply = _finalize_reply(reply, turns, bcp47, fields=fields, vertical=vertical)
    call.captured_fields = fields
    _append_and_save(db, call, turns, text, reply, hangup=hangup)
    logger.info(
        "inbound_turn booking_state=%s",
        booking_state_trace_summary(load_booking(call.captured_fields)),
    )
    return reply, hangup


def _append_and_save(
    db: Session,
    call: Call,
    turns: list[dict[str, str]],
    user_text: str,
    agent_text: str,
    *,
    hangup: bool,
) -> None:
    turns.append({"role": "user", "text": user_text})
    turns.append({"role": "assistant", "text": agent_text})
    transcript_lines = []
    for t in turns:
        who = "Caller" if t["role"] == "user" else "KARYUK"
        transcript_lines.append(f"{who}: {t['text']}")
    call.transcript = "\n".join(transcript_lines)
    call.summary = agent_text[:500]
    booking_blob = (call.captured_fields or {}).get(BOOKING_KEY)
    call.captured_fields = {
        **(call.captured_fields or {}),
        "inbound_chat": {"turns": turns},
    }
    if booking_blob:
        call.captured_fields[BOOKING_KEY] = booking_blob
    if hangup:
        call.outcome = CallOutcome.completed
        call.finalized_at = datetime.now(UTC)
        call.duration_seconds = max(call.duration_seconds, len(turns) * 15)
    db.commit()
    db.refresh(call)