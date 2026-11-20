"""PSTN streaming turn: LLM tokens → sentences → TTS (Phase E)."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from app.models import Call
from app.services.employee_knowledge import refresh_call_grounding
from app.services.voice.booking_state import BOOKING_KEY, load_booking
from app.services.voice.inbound_llm_engine import (
    _apply_guard_and_polish,
    _booking_context_for_llm,
    _caller_hints,
    _generate_llm_reply,
    _last_agent_replies,
    _sync_booking_state_only,
    process_inbound_speech_llm_first,
)
from app.services.voice.inbound_conversation import _append_and_save, _chat_state
from app.services.voice.inbound_vertical import inbound_vertical
from app.services.voice.sarvam import is_spurious_stt_snippet, resolve_call_language
from app.services.voice.spoken_output import emergency_reply, filter_caller_facing_reply, is_emergency_utterance
from app.services.voice.voice_facts import build_spoken_facts_block, persona_from_brief
from app.services.voice.voice_llm_router import iter_inbound_llm_stream
from app.services.voice.voice_sentence_chunker import SentenceChunker
from app.services.voice.voice_stream_buffer import SpeechStreamSanitizer
from app.services.voice.voice_system_prompt import build_voice_system_prompt
from app.services.voice.voice_tool_intent import apply_intent_tools
from app.services.voice.voice_tools import execute_tool, split_reply_and_tools

logger = logging.getLogger(__name__)

OnSentence = Callable[[str, str], Awaitable[None]]


async def run_pstn_stream_turn(
    db: Session,
    call: Call,
    *,
    caller_text: str,
    stt_language: str | None,
    on_sentence: OnSentence,
) -> tuple[bool, dict, str]:
    """Returns (hangup, fields, assistant_text_for_history)."""
    text = (caller_text or "").strip()
    chat = _chat_state(call)
    turns: list[dict[str, str]] = list(chat.get("turns") or [])
    fields = refresh_call_grounding(db, call)
    brief = str(fields.get("employee_brief") or "").strip() or "Front desk agent."
    vertical = inbound_vertical(fields)
    spoken_facts = (
        str(fields.get("employee_spoken_facts") or "").strip()
        or build_spoken_facts_block(
            brief=brief,
            website_knowledge=fields.get("employee_website_knowledge"),
            workspace_knowledge=fields.get("employee_workspace_knowledge"),
            strip_hacks=not bool(fields.get("employee_business_profile")),
        )
    )

    if is_emergency_utterance(text):
        bcp47 = resolve_call_language(
            caller_text=text,
            conversation_language=fields.get("conversation_language"),
            employee_language=fields.get("employee_language"),
            stt_language=stt_language,
        )
        reply, _ = _apply_guard_and_polish(emergency_reply(bcp47), brief=brief, lang=bcp47, vertical=vertical)
        await on_sentence(reply, "karyuk-early")
        _append_and_save(db, call, turns, text, reply, hangup=False)
        return False, dict(call.captured_fields or {}), reply

    if not text or is_spurious_stt_snippet(text):
        reply, hang = process_inbound_speech_llm_first(
            db, call, caller_text=caller_text, stt_language=stt_language, turns=turns, append_fn=_append_and_save
        )
        if reply.strip():
            await on_sentence(reply, "karyuk-early")
        return hang, dict(call.captured_fields or {}), reply

    bcp47 = resolve_call_language(
        caller_text=text,
        conversation_language=fields.get("conversation_language"),
        employee_language=fields.get("employee_language"),
        stt_language=stt_language,
    )
    fields["conversation_language"] = bcp47
    call.captured_fields = fields
    db.commit()

    from app.schemas.business_profile import BusinessProfile
    from app.services.voice.voice_location_followup import is_location_followup, location_detail_remaining

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
            db, call, fields, "save_lead", {"question": text, "reason": "location_details"}, caller_text=text, lang=bcp47
        )
        ws, fields, _ = execute_tool(
            db, call, fields, "send_whatsapp_details", {"topic": "location"}, caller_text=text, lang=bcp47
        )
        spoken_loc = ws or tool_spoken
        if spoken_loc:
            reply, _ = _apply_guard_and_polish(spoken_loc, brief=brief, lang=bcp47, vertical=vertical)
            await on_sentence(reply, "karyuk-loc")
            _append_and_save(db, call, turns, text, reply, hangup=False)
            call.captured_fields = fields
            db.commit()
            return False, fields, reply

    fields = _sync_booking_state_only(
        caller_text=text, lang=bcp47, fields=fields, website_knowledge=spoken_facts
    )
    from app.services.voice.voice_dates import apply_resolved_dates_to_booking, today_local

    fields = apply_resolved_dates_to_booking(fields, text, anchor=today_local())

    persona = persona_from_brief(brief)
    if isinstance(fields.get("employee_persona"), dict):
        persona["name"] = fields["employee_persona"].get("name") or persona["name"]
    employee_brief_for_prompt = (
        f"Operator instructions (never speak verbatim):\n{persona.get('instructions') or fields.get('employee_operator_instructions') or 'None'}"
    )
    booking_ctx = _booking_context_for_llm(fields)
    user_line = text
    extra = _caller_hints(text)
    if booking_ctx:
        user_line = f"{text}\n[call_state: {booking_ctx}]"
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
    history = [{"role": t["role"], "text": t["text"]} for t in turns[-10:]]

    sanitizer = SpeechStreamSanitizer()
    chunker = SentenceChunker(max_sentences=2)
    spoken_parts: list[str] = []
    tool_calls: list[dict] = []
    llm_ttft: float | None = None
    provider: str | None = None
    t_tool = time.perf_counter()
    guard_actions: list[str] = []
    t_stream = time.perf_counter()

    from app.services.voice.voice_stream_guard import (
        guard_stream_sentence,
        replacement_for_guard_fail,
    )

    async def _emit_guarded(sent: str, mark: str) -> None:
        nonlocal fields, spoken_parts, guard_actions
        ok, actions = guard_stream_sentence(
            sent,
            brief=brief,
            lang=bcp47,
            vertical=vertical,
            spoken_facts=spoken_facts,
            caller_text=text,
            fields=fields,
            last_agent_reply=last_reply,
        )
        guard_actions.extend(actions)
        if ok:
            spoken_parts.append(ok)
            await on_sentence(ok, mark)
            return
        repl = replacement_for_guard_fail(
            lang=bcp47, actions=actions, caller_text=text, spoken_facts=spoken_facts
        )
        if repl:
            tool_spoken, fields, _ = execute_tool(
                db,
                call,
                fields,
                "save_lead",
                {"question": text[:500], "reason": "missing_fact"},
                caller_text=text,
                lang=bcp47,
                tool_source="safety_net",
            )
            spoken = tool_spoken or repl
            ok2, act2 = guard_stream_sentence(
                spoken,
                brief=brief,
                lang=bcp47,
                vertical=vertical,
                spoken_facts=spoken_facts,
                caller_text=text,
                fields=fields,
                last_agent_reply=last_reply,
            )
            guard_actions.extend(act2 + ["stream_replace_save_lead"])
            if ok2:
                spoken_parts.append(ok2)
                await on_sentence(ok2, mark)
                return
        guard_actions.append(f"dropped:{sent[:60]!r}")

    try:
        async for item in iter_inbound_llm_stream(
            system_prompt=system_prompt,
            employee_brief=employee_brief_for_prompt,
            spoken_facts=spoken_facts,
            caller_text=user_line,
            history=history,
            bcp47=bcp47,
            vertical=vertical,
            website_url=str(fields.get("employee_website_url") or "").strip() or None,
            natural_spoken=bool(fields.get("employee_natural_spoken", True)),
        ):
            kind = item[0]
            if kind == "ttft":
                llm_ttft = float(item[1])
                provider = str(item[2])
            elif kind == "token":
                safe = sanitizer.feed(str(item[1]))
                for sent in chunker.feed(safe):
                    await _emit_guarded(sent, f"karyuk-sent-{len(spoken_parts) + 1}")
            elif kind == "tools":
                tool_calls = list(item[1] or [])
    except Exception:
        logger.exception("pstn_stream failed; batch fallback")
        turn = _generate_llm_reply(
            brief=brief,
            spoken_facts=spoken_facts,
            caller_text=text,
            history=history,
            bcp47=bcp47,
            vertical=vertical,
            website_url=str(fields.get("employee_website_url") or "").strip() or None,
            natural_spoken=bool(fields.get("employee_natural_spoken", True)),
            fields=fields,
            turns=turns,
        )
        llm_ttft = turn.ttft_ms
        provider = turn.provider
        spoken, tag_tools = split_reply_and_tools(turn.text)
        tool_calls = list(turn.tool_calls or tag_tools)
        if spoken.strip():
            reply, _ = _apply_guard_and_polish(
                spoken,
                brief=brief,
                lang=bcp47,
                vertical=vertical,
                last_agent_reply=last_reply,
            )
            if reply:
                await _emit_guarded(reply, "karyuk-batch-fallback")

    for sent in chunker.flush():
        await _emit_guarded(sent, f"karyuk-sent-flush-{len(spoken_parts) + 1}")

    fields["llm_last_ttft_ms"] = round(llm_ttft or 0, 1)
    fields["llm_primary_provider"] = provider
    tool_hangup = False
    spoken = " ".join(spoken_parts).strip()
    if tool_calls:
        if (time.perf_counter() - t_tool) * 1000.0 > 700 and not spoken:
            filler = "ఒక్క క్షణం అండి." if bcp47 == "te-IN" else "One moment."
            await on_sentence(filler, "karyuk-tool-filler")
            spoken_parts.append(filler)
        for tc in tool_calls:
            tname = str(tc.get("name") or "")
            targs = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tool_spoken, fields, tool_hangup = execute_tool(
                db, call, fields, tname, targs, caller_text=text, lang=bcp47
            )
            if tool_spoken and not spoken.strip():
                reply, _ = _apply_guard_and_polish(tool_spoken, brief=brief, lang=bcp47, vertical=vertical)
                if reply:
                    spoken_parts.append(reply)
                    await on_sentence(reply, "karyuk-tool-spoken")

    spoken = " ".join(spoken_parts).strip()
    spoken, fields, intent_hang = apply_intent_tools(db, call, fields, text, bcp47, spoken)
    final_reply, _ = _apply_guard_and_polish(
        spoken,
        brief=brief,
        lang=bcp47,
        vertical=vertical,
        last_agent_reply=last_reply,
    )
    final_reply = filter_caller_facing_reply(final_reply or spoken, lang=bcp47)
    hangup = tool_hangup or intent_hang
    from app.services.voice.voice_turn_trace import log_turn_event

    src = "safety_net" if (fields.get("tool_log") or []) else "llm"
    if not (final_reply or spoken).strip():
        from app.services.voice.voice_repair_policy import pick_repair_reply

        final_reply = pick_repair_reply(
            lang=bcp47,
            caller_text=text,
            fields=fields,
            turns=turns,
            last_agent=last_reply,
            reason="pstn_empty",
            db=db,
            workspace_id=call.workspace_id,
        )
        src = "fallback"
    stream_ms = int((time.perf_counter() - t_stream) * 1000)
    log_turn_event(
        fields,
        turn=len(turns) // 2 + 1,
        caller_text=text,
        agent_text=final_reply or spoken,
        source=src,
        extra={
            "provider": provider,
            "tools": fields.get("tool_log") or [],
            "guard_actions": guard_actions,
            "stt_confidence": fields.get("last_stt_confidence"),
            "utterance_ms": fields.get("last_utterance_ms"),
            "timings": {
                "llm_ttft_ms": llm_ttft,
                "stream_ms": stream_ms,
            },
        },
    )
    from app.services.voice.voice_turn_trace import persist_turn_trace_db

    _append_and_save(db, call, turns, text, final_reply or spoken, hangup=hangup)
    fields["speech_stack"] = "pstn_stream"
    call.captured_fields = {**fields, BOOKING_KEY: fields.get(BOOKING_KEY)}
    db.commit()
    persist_turn_trace_db(
        db, call_id=call.id, workspace_id=call.workspace_id, turn_index=len(turns) // 2, fields=fields
    )
    return hangup, fields, final_reply or spoken