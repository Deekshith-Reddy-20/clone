"""LLM-first inbound speech (Phase A). Deterministic code: safety I/O, hangup, booking state sync, guard."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Call
from app.models.enums import CallOutcome
from app.services.employee_knowledge import refresh_call_grounding
from app.services.voice.booking_state import (
    BOOKING_KEY,
    booking_intent_utterance,
    dump_booking,
    load_booking,
)
from app.services.voice.voice_llm_router import LlmTurnResult, generate_inbound_llm_turn
from app.services.voice.voice_system_prompt import build_voice_system_prompt
from app.services.voice.voice_tool_intent import apply_intent_tools
from app.services.voice.voice_tools import execute_tool, split_reply_and_tools
from app.services.voice.inbound_booking import try_booking_turn
from app.services.voice.inbound_vertical import inbound_vertical
from app.services.voice.sarvam import is_clarify_fallback, is_spurious_stt_snippet, resolve_call_language
from app.services.voice.spoken_output import emergency_reply, filter_caller_facing_reply, is_emergency_utterance
from app.services.voice.spoken_length import cap_spoken_reply, enforce_brevity
from app.services.voice.sarvam import sanitize_reply_for_lang
from app.services.voice.voice_facts import build_spoken_facts_block, persona_from_brief
from app.services.voice.voice_fact_guard import (
    caller_asks_missing_fact,
    reply_invented_negative,
    reply_mentions_ungrounded_entity,
)
from app.services.voice.voice_dates import apply_resolved_dates_to_booking, today_local
from app.services.voice.voice_output_guard import guard_reply_rejected, llm_hard_fallback
from app.services.voice.voice_repair_policy import (
    frustration_closing,
    is_frustration_utterance,
    llm_closing_instruction,
    pick_repair_reply,
)
from app.services.voice.voice_turn_trace import log_turn_event
from app.services.voice.voice_safety_net import (
    availability_action_intent,
    booking_create_intent,
    safety_net_blocked,
    visit_action_intent,
)
from app.services.voice.voice_booking_slots import (
    append_missing_slot_if_needed,
    apply_slot_merge,
    format_booking_slot_block,
    handle_booking_slot_turn,
    llm_booking_turn_suffix,
    lodging_booking_call,
    missing_booking_slots,
)

logger = logging.getLogger(__name__)

MAX_TURNS = 14


def llm_first_enabled() -> bool:
    return os.getenv("KARYUK_VOICE_LLM_FIRST", "1").strip() not in ("0", "false", "no")


def _sync_booking_state_only(
    *,
    caller_text: str,
    lang: str,
    fields: dict,
    website_knowledge: str | None,
    last_agent_reply: str | None = None,
) -> dict:
    """Update lodging/hospital booking state without speaking template replies."""
    if lodging_booking_call(fields):
        return fields
    try_booking_turn(
        caller_text=caller_text,
        lang=lang,
        fields=fields,
        website_knowledge=website_knowledge,
    )
    fields = apply_resolved_dates_to_booking(fields, caller_text, anchor=today_local())
    return fields


def _booking_context_for_llm(fields: dict) -> str:
    from app.services.voice.voice_booking_slots import format_booking_slot_block

    return format_booking_slot_block(load_booking(fields), fields)


def _last_agent_replies(turns: list[dict[str, str]]) -> list[str]:
    return [t["text"] for t in turns if t.get("role") == "assistant"][-3:]


def _caller_hints(caller_text: str) -> str:
    t = (caller_text or "").strip()
    hints: list[str] = []
    low = t.lower()
    if any(k in low for k in ("which resort", "what resort", "ఏ resort", "ఏ రిజార్ట్")):
        hints.append("[hint: identity = business name + one hook + one question only, ~20 words]")
    from app.services.voice.voice_safety_net import manager_callback_intent

    if manager_callback_intent(t):
        hints.append('[hint: use tool transfer_to_human if they insist]')
    if any(k in low for k in ("don't know", "not sure", "లేదు", "తెలీదు")) and len(t) < 120:
        hints.append("[hint: save_lead for unknown detail]")
    return "\n".join(hints)


def _generate_llm_reply(
    *,
    brief: str,
    spoken_facts: str,
    caller_text: str,
    history: list[dict[str, str]],
    bcp47: str,
    vertical: str,
    website_url: str | None,
    natural_spoken: bool,
    fields: dict,
    turns: list[dict[str, str]],
) -> LlmTurnResult:
    persona = persona_from_brief(brief)
    if isinstance(fields.get("employee_persona"), dict):
        persona["name"] = fields["employee_persona"].get("name") or persona["name"]
    employee_brief_for_prompt = (
        f"Operator instructions (never speak verbatim):\n{persona.get('instructions') or fields.get('employee_operator_instructions') or 'None'}"
    )
    from app.services.voice.employee_playbook import booking_flow_active

    st = load_booking(fields)
    user_line = caller_text
    extra = _caller_hints(caller_text)
    if lodging_booking_call(fields) and (
        booking_flow_active(fields) or st.check_in or booking_intent_utterance(caller_text)
    ):
        block = format_booking_slot_block(st, fields)
        user_line = f"{caller_text}\n{block}\n{llm_booking_turn_suffix(st, fields, bcp47)}"
    else:
        booking_ctx = _booking_context_for_llm(fields)
        if booking_ctx:
            user_line = f"{caller_text}\n[call_state: {booking_ctx}]"
    if extra:
        user_line = f"{user_line}\n{extra}"

    system_prompt = build_voice_system_prompt(
        persona_name=persona["name"],
        business_name=persona["business"],
        facts=spoken_facts,
        reply_language=bcp47,
        vertical=vertical,
        profile=fields.get("employee_business_profile"),
        last_agent_replies=_last_agent_replies(turns),
    )
    return generate_inbound_llm_turn(
        system_prompt=system_prompt,
        employee_brief=employee_brief_for_prompt,
        spoken_facts=spoken_facts,
        caller_text=user_line,
        history=history,
        bcp47=bcp47,
        vertical=vertical,
        website_url=website_url,
        natural_spoken=natural_spoken,
    )


def _apply_guard_and_polish(
    reply: str,
    *,
    brief: str,
    lang: str,
    vertical: str,
    last_agent_reply: str | None = None,
) -> tuple[str, bool]:
    from app.services.voice.voice_booking_slots import collapse_repeated_spoken

    reply = filter_caller_facing_reply((reply or "").strip(), lang=lang)
    reply = collapse_repeated_spoken(reply)
    reply = sanitize_reply_for_lang(reply, lang, vertical=vertical)
    reply, needs_regen = enforce_brevity(reply)
    if needs_regen:
        return "", True
    reply, rejected = guard_reply_rejected(
        reply, brief=brief, lang=lang, last_agent_reply=last_agent_reply
    )
    if rejected:
        return "", True
    # Still identical to last agent line after polish → don't re-speak the same words.
    if last_agent_reply and reply.strip() == last_agent_reply.strip():
        return "", True
    return cap_spoken_reply(reply, max_chars=220), False


def process_inbound_speech_llm_first(
    db: Session,
    call: Call,
    *,
    caller_text: str,
    stt_language: str | None,
    turns: list[dict[str, str]],
    append_fn,
) -> tuple[str, bool]:
    text = (caller_text or "").strip()
    fields = refresh_call_grounding(db, call)
    emp_lang = fields.get("employee_language")
    conv_lang = fields.get("conversation_language")
    vertical = inbound_vertical(fields)
    brief = str(fields.get("employee_brief") or "").strip() or "Front desk agent."
    spoken_facts = (
        str(fields.get("employee_spoken_facts") or "").strip()
        or build_spoken_facts_block(
            brief=brief,
            website_knowledge=fields.get("employee_website_knowledge"),
            workspace_knowledge=fields.get("employee_workspace_knowledge"),
            strip_hacks=not bool(fields.get("employee_business_profile")),
        )
    )
    op_inst = str(fields.get("employee_operator_instructions") or "").strip()
    if op_inst:
        brief = f"{brief}\n[operator]\n{op_inst}"
    web_url = str(fields.get("employee_website_url") or "").strip() or None
    natural = bool(fields.get("employee_natural_spoken", True))

    if is_emergency_utterance(text):
        bcp47 = resolve_call_language(
            caller_text=text,
            conversation_language=conv_lang,
            employee_language=emp_lang,
            stt_language=stt_language,
        )
        reply, _ = _apply_guard_and_polish(emergency_reply(bcp47), brief=brief, lang=bcp47, vertical=vertical)
        fields["conversation_language"] = bcp47
        call.captured_fields = fields
        append_fn(db, call, turns, text, reply, hangup=False)
        return reply, False

    if not text:
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

    if is_spurious_stt_snippet(text):
        lang = resolve_call_language(
            caller_text=text,
            conversation_language=conv_lang,
            employee_language=emp_lang,
            stt_language=stt_language,
        )
        retries = {
            "te-IN": "క్షమించండి, స్పష్టంగా వినిపించలేదు. మళ్ళీ చెప్పండి.",
            "hi-IN": "माफ़ कीजिए, मुझे साफ़ सुनाई नहीं दिया।",
            "en-IN": "Sorry, I did not catch that clearly. Please say that again.",
        }
        reply, _ = _apply_guard_and_polish(retries.get(lang, retries["en-IN"]), brief=brief, lang=lang, vertical=vertical)
        fields["conversation_language"] = lang
        call.captured_fields = fields
        append_fn(db, call, turns, text, reply, hangup=False)
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
    )
    # Only hang up on clear goodbye — not on "thanks" / short acks after noting a request.
    if any(p in lowered for p in hangup_phrases) or "అంతే చాలు" in text:
        bye = {
            "te-IN": "సరే అండి, థ్యాంక్యూ.",
            "hi-IN": "ठीक है जी, धन्यवाद।",
            "en-IN": "Sure, thank you.",
        }
        reply = bye.get(bcp47, bye["en-IN"])
        append_fn(db, call, turns, text, reply, hangup=True)
        return reply, True

    if len(turns) >= MAX_TURNS * 2:
        if is_frustration_utterance(text):
            reply = frustration_closing(lang=bcp47, fields=fields, db=db, workspace_id=call.workspace_id)
            append_fn(db, call, turns, text, reply, hangup=False)
            log_turn_event(fields, turn=len(turns) // 2 + 1, caller_text=text, agent_text=reply, source="frustration_close")
            call.captured_fields = fields
            return reply, False
        turn = _generate_llm_reply(
            brief=brief,
            spoken_facts=spoken_facts,
            caller_text=text + "\n" + llm_closing_instruction(bcp47),
            history=[{"role": t["role"], "text": t["text"]} for t in turns[-10:]],
            bcp47=bcp47,
            vertical=vertical,
            website_url=web_url,
            natural_spoken=natural,
            fields=fields,
            turns=turns,
        )
        reply = (turn.text or "").strip() or frustration_closing(
            lang=bcp47, fields=fields, db=db, workspace_id=call.workspace_id
        )
        reply, _ = _apply_guard_and_polish(reply, brief=brief, lang=bcp47, vertical=vertical)
        append_fn(db, call, turns, text, reply, hangup=True)
        log_turn_event(fields, turn=len(turns) // 2 + 1, caller_text=text, agent_text=reply, source="end_call")
        call.captured_fields = fields
        return reply, True

    last_reply = _last_agent_replies(turns)[-1] if _last_agent_replies(turns) else None
    miss_before: list[str] = []
    if lodging_booking_call(fields):
        st0 = load_booking(fields)
        miss_before = missing_booking_slots(st0, fields)
        fields = apply_slot_merge(fields, text, last_agent_reply=last_reply)
    else:
        fields = _sync_booking_state_only(
            caller_text=text,
            lang=bcp47,
            fields=fields,
            website_knowledge=spoken_facts,
            last_agent_reply=last_reply,
        )
    call.captured_fields = {**fields, BOOKING_KEY: fields.get(BOOKING_KEY)}

    def _slot_tool(name: str, args: dict, tool_source: str = "slot_flow"):
        return execute_tool(
            db,
            call,
            fields,
            name,
            args,
            caller_text=text,
            lang=bcp47,
            tool_source=tool_source,
        )

    def slot_exec(name: str, args: dict, tool_source: str = "slot_flow"):
        spoken, f2, hang = _slot_tool(name, args, tool_source)
        nonlocal fields
        fields = f2
        return spoken, fields, hang

    slot_reply, fields, slot_hangup = handle_booking_slot_turn(
        db,
        call,
        fields,
        text,
        bcp47,
        last_reply,
        slot_exec,
        miss_before=miss_before,
    )
    if slot_reply:
        polished, rej = _apply_guard_and_polish(
            slot_reply, brief=brief, lang=bcp47, vertical=vertical, last_agent_reply=last_reply
        )
        slot_reply = polished or slot_reply
        if rej and not slot_reply.strip():
            from app.services.voice.voice_booking_slots import ask_line_for_slot, next_missing_slot

            miss = next_missing_slot(load_booking(fields), fields)
            slot_reply = ask_line_for_slot(miss or "confirm", bcp47, load_booking(fields))
        fields["speech_stack"] = "llm_first"
        fields["turn_source"] = "booking_slots"
        log_turn_event(
            fields,
            turn=len(turns) // 2 + 1,
            caller_text=text,
            agent_text=slot_reply,
            source="booking_slots",
        )
        call.captured_fields = fields
        append_fn(db, call, turns, text, slot_reply, hangup=slot_hangup)
        return slot_reply, slot_hangup

    from app.schemas.business_profile import BusinessProfile
    from app.services.voice.voice_location_followup import (
        is_location_followup,
        location_detail_remaining,
    )

    profile = BusinessProfile.from_snapshot(fields.get("employee_business_profile"))
    last_reply = _last_agent_replies(turns)[-1] if _last_agent_replies(turns) else ""
    has_loc = bool(
        profile.location.landmarks
        or profile.location.directions
        or profile.location.maps_link
        or profile.location.full_address
    )
    if is_location_followup(text) and has_loc and not location_detail_remaining(profile, last_reply):
        tool_spoken, fields, _ = execute_tool(
            db,
            call,
            fields,
            "save_lead",
            {"question": text, "reason": "location_details"},
            caller_text=text,
            lang=bcp47,
            tool_source="safety_net",
        )
        spoken_loc = tool_spoken
        if spoken_loc:
            reply, _ = _apply_guard_and_polish(spoken_loc, brief=brief, lang=bcp47, vertical=vertical)
            fields["speech_stack"] = "llm_first"
            call.captured_fields = fields
            append_fn(db, call, turns, text, reply, hangup=False)
            return reply, False

    history = [{"role": t["role"], "text": t["text"]} for t in turns[-10:]]
    last_reply = _last_agent_replies(turns)[-1] if _last_agent_replies(turns) else None
    turn = _generate_llm_reply(
        brief=brief,
        spoken_facts=spoken_facts,
        caller_text=text,
        history=history,
        bcp47=bcp47,
        vertical=vertical,
        website_url=web_url,
        natural_spoken=natural,
        fields=fields,
        turns=turns,
    )
    fields["llm_last_ttft_ms"] = round(turn.ttft_ms, 1)
    fields["llm_primary_provider"] = turn.provider
    if turn.failover_reason:
        fields["llm_last_failover"] = {
            "from": turn.failover_from,
            "reason": turn.failover_reason,
        }
        log = list(fields.get("llm_failover_log") or [])
        log.append(fields["llm_last_failover"])
        fields["llm_failover_log"] = log[-10:]

    raw = turn.text
    if is_clarify_fallback(raw, bcp47, vertical=vertical):
        raw = ""

    spoken, tool_calls = split_reply_and_tools(raw)
    if turn.tool_calls:
        tool_calls = [*tool_calls, *[{"name": c.get("name"), "args": c.get("args") or {}} for c in turn.tool_calls]]
    tool_hangup = False
    for tc in tool_calls:
        tname = str(tc.get("name") or "")
        targs = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        tool_spoken, fields, tool_hangup = execute_tool(
            db,
            call,
            fields,
            tname,
            targs,
            caller_text=text,
            lang=bcp47,
            tool_source="llm_native",
        )
        if tool_spoken and not spoken.strip():
            spoken = tool_spoken

    spoken, fields, intent_hang = apply_intent_tools(db, call, fields, text, bcp47, spoken)
    tool_hangup = tool_hangup or intent_hang

    tool_names = [str(t.get("name")) for t in (fields.get("tool_log") or [])]
    if (
        not lodging_booking_call(fields)
        and not safety_net_blocked(text)
        and availability_action_intent(text)
        and "check_availability" not in tool_names
    ):
        tool_spoken, fields, _ = execute_tool(
            db,
            call,
            fields,
            "check_availability",
            {"dates": text[:200]},
            caller_text=text,
            lang=bcp47,
            tool_source="safety_net",
        )
        if tool_spoken and not spoken.strip():
            spoken = tool_spoken
        tool_names = [str(t.get("name")) for t in (fields.get("tool_log") or [])]
    if (
        not lodging_booking_call(fields)
        and not safety_net_blocked(text)
        and visit_action_intent(text)
        and not any(n in tool_names for n in ("save_lead", "check_availability", "create_booking"))
    ):
        tool_spoken, fields, _ = execute_tool(
            db,
            call,
            fields,
            "check_availability",
            {"dates": text[:200]},
            caller_text=text,
            lang=bcp47,
            tool_source="safety_net",
        )
        if tool_spoken and not spoken.strip():
            spoken = tool_spoken
        tool_names = [str(t.get("name")) for t in (fields.get("tool_log") or [])]
    from app.services.voice.employee_playbook import booking_flow_active

    if (
        not lodging_booking_call(fields)
        and not safety_net_blocked(text)
        and booking_create_intent(text, fields)
        and "create_booking" not in tool_names
    ):
        st = load_booking(fields)
        tool_spoken, fields, tool_hangup = execute_tool(
            db,
            call,
            fields,
            "create_booking",
            {
                "confirmed_verbal": True,
                "check_in": st.check_in,
                "check_out": st.check_out,
                "guests": st.guest_count,
            },
            caller_text=text,
            lang=bcp47,
            tool_source="safety_net",
        )
        if tool_spoken:
            spoken = tool_spoken if not spoken.strip() else spoken
        tool_names = [str(t.get("name")) for t in (fields.get("tool_log") or [])]
    if (
        caller_asks_missing_fact(text, spoken_facts)
        and not safety_net_blocked(text)
        and "save_lead" not in tool_names
    ):
        sl_spoken, fields, _ = execute_tool(
            db,
            call,
            fields,
            "save_lead",
            {"question": text[:500], "reason": "missing_fact"},
            caller_text=text,
            lang=bcp47,
            tool_source="safety_net",
        )
        if sl_spoken:
            spoken = sl_spoken

    reply, guard_rej = _apply_guard_and_polish(
        spoken,
        brief=brief,
        lang=bcp47,
        vertical=vertical,
        last_agent_reply=last_reply,
    )
    if guard_rej:
        fields["llm_guard_rejections"] = int(fields.get("llm_guard_rejections") or 0) + 1
    from app.services.voice.voice_grounding_guard import apply_grounding_to_reply

    if reply:
        grounded, greasons = apply_grounding_to_reply(
            reply, spoken_facts=spoken_facts, fields=fields, caller_text=text
        )
        if greasons:
            fields["llm_grounding_block"] = int(fields.get("llm_grounding_block") or 0) + 1
            fields["llm_grounding_reasons"] = greasons[-8:]
        if grounded != reply:
            slot_block = _booking_context_for_llm(fields)
            regen = _generate_llm_reply(
                brief=brief,
                spoken_facts=spoken_facts,
                caller_text=(
                    f"{text}\n[GROUNDING_FAIL: {','.join(greasons)}]\n{slot_block}\n"
                    "[Use only BOOKING slot state. Do not invent dates or availability.]"
                ),
                history=history,
                bcp47=bcp47,
                vertical=vertical,
                website_url=web_url,
                natural_spoken=natural,
                fields=fields,
                turns=turns,
            )
            regen_spoken, _ = split_reply_and_tools(regen.text)
            regen_spoken, rj = _apply_guard_and_polish(
                regen_spoken, brief=brief, lang=bcp47, vertical=vertical, last_agent_reply=last_reply
            )
            regrounded, rreasons = apply_grounding_to_reply(
                regen_spoken, spoken_facts=spoken_facts, fields=fields, caller_text=text
            )
            if rreasons and not regrounded.strip():
                from app.services.voice.voice_booking_slots import (
                    ask_line_for_slot,
                    next_missing_slot,
                )

                miss = next_missing_slot(load_booking(fields), fields)
                reply = (
                    ask_line_for_slot(miss, bcp47, load_booking(fields))
                    if miss
                    else grounded
                )
            else:
                reply = regrounded or grounded
            if greasons and reply == grounded:
                reason = "ungrounded_claim"
                if "amenity_ungrounded" in greasons or "invented_negative" in greasons:
                    reason = "unknown_amenity"
                _, fields, _ = execute_tool(
                    db,
                    call,
                    fields,
                    "save_lead",
                    {"question": text[:500], "reason": reason},
                    caller_text=text,
                    lang=bcp47,
                    tool_source="safety_net",
                )
    if reply and reply_mentions_ungrounded_entity(reply, spoken_facts):
        fields["llm_fact_hallucination"] = int(fields.get("llm_fact_hallucination") or 0) + 1
        if reply_invented_negative(reply, spoken_facts):
            fields["llm_invented_negative"] = int(fields.get("llm_invented_negative") or 0) + 1
        turn2 = _generate_llm_reply(
            brief=brief,
            spoken_facts=spoken_facts,
            caller_text=text + "\n[That fact is not in FACTS — use save_lead; do not say X లేదు unless FACTS says so.]",
            history=history,
            bcp47=bcp47,
            vertical=vertical,
            website_url=web_url,
            natural_spoken=natural,
            fields=fields,
            turns=turns,
        )
        fields["llm_last_ttft_ms"] = round(turn2.ttft_ms, 1)
        fields["llm_primary_provider"] = turn2.provider
        spoken2, tools2 = split_reply_and_tools(turn2.text)
        if turn2.tool_calls:
            tools2 = [
                *tools2,
                *[{"name": c.get("name"), "args": c.get("args") or {}} for c in turn2.tool_calls],
            ]
        for tc in tools2:
            tool_spoken, fields, tool_hangup = execute_tool(
                db,
                call,
                fields,
                str(tc.get("name") or ""),
                tc.get("args") if isinstance(tc.get("args"), dict) else {},
                caller_text=text,
                lang=bcp47,
                tool_source="llm_native",
            )
            if tool_spoken and not spoken2.strip():
                spoken2 = tool_spoken
        spoken2, fields, intent_hang = apply_intent_tools(db, call, fields, text, bcp47, spoken2)
        tool_hangup = tool_hangup or intent_hang
        reply, guard_rej = _apply_guard_and_polish(
            spoken2,
            brief=brief,
            lang=bcp47,
            vertical=vertical,
            last_agent_reply=last_reply,
        )
        if guard_rej:
            fields["llm_guard_rejections"] = int(fields.get("llm_guard_rejections") or 0) + 1
    if reply and reply_invented_negative(reply, spoken_facts) and caller_asks_missing_fact(
        text, spoken_facts
    ):
        _, fields, _ = execute_tool(
            db,
            call,
            fields,
            "save_lead",
            {"question": text[:500], "reason": "missing_fact"},
            caller_text=text,
            lang=bcp47,
            tool_source="safety_net",
        )
        reply = (
            "confirm చేసి చెప్తాము అండి — మా team note చేస్తారు."
            if bcp47 == "te-IN"
            else "We'll confirm and get back to you."
        )
    if not reply:
        turn2 = _generate_llm_reply(
            brief=brief,
            spoken_facts=spoken_facts,
            caller_text=text + "\n[guard_retry: max 2 sentences ~25 words, FACTS only, new detail]",
            history=history,
            bcp47=bcp47,
            vertical=vertical,
            website_url=web_url,
            natural_spoken=natural,
            fields=fields,
            turns=turns,
        )
        fields["llm_last_ttft_ms"] = round(turn2.ttft_ms, 1)
        fields["llm_primary_provider"] = turn2.provider
        spoken2, tools2 = split_reply_and_tools(turn2.text)
        if turn2.tool_calls:
            tools2 = [
                *tools2,
                *[{"name": c.get("name"), "args": c.get("args") or {}} for c in turn2.tool_calls],
            ]
        for tc in tools2:
            tool_spoken, fields, tool_hangup = execute_tool(
                db,
                call,
                fields,
                str(tc.get("name") or ""),
                tc.get("args") if isinstance(tc.get("args"), dict) else {},
                caller_text=text,
                lang=bcp47,
                tool_source="llm_native",
            )
            if tool_spoken and not spoken2.strip():
                spoken2 = tool_spoken
        reply, guard_rej2 = _apply_guard_and_polish(
            spoken2,
            brief=brief,
            lang=bcp47,
            vertical=vertical,
            last_agent_reply=last_reply,
        )
        if guard_rej2:
            fields["llm_guard_rejections"] = int(fields.get("llm_guard_rejections") or 0) + 1
    if not reply:
        reply = pick_repair_reply(
            lang=bcp47,
            caller_text=text,
            fields=fields,
            turns=turns,
            last_agent=_last_agent_replies(turns)[-1] if _last_agent_replies(turns) else None,
            reason="empty_after_guard",
            db=db,
            workspace_id=call.workspace_id,
        )
        fields["llm_hard_fallbacks"] = int(fields.get("llm_hard_fallbacks") or 0) + 1
        source = "fallback"
    else:
        source = "llm"

    from app.services.voice.employee_playbook import booking_flow_active

    if (
        reply
        and lodging_booking_call(fields)
        and booking_flow_active(fields)
        and source == "llm"
    ):
        reply = append_missing_slot_if_needed(reply, fields, bcp47)

    fields["speech_stack"] = "llm_first"
    log_turn_event(
        fields,
        turn=len(turns) // 2 + 1,
        caller_text=text,
        agent_text=reply,
        source=source,
        extra={"provider": fields.get("llm_primary_provider")},
    )
    from app.services.voice.voice_turn_trace import persist_turn_trace_db

    call.captured_fields = fields
    hangup = tool_hangup or ("goodbye" in reply.lower() and len(turns) > 2)
    append_fn(db, call, turns, text, reply, hangup=hangup)
    persist_turn_trace_db(
        db, call_id=call.id, workspace_id=call.workspace_id, turn_index=len(turns) // 2, fields=fields
    )
    return reply, hangup