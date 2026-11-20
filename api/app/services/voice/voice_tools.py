"""Voice agent tools (Phase D) — invoked from LLM tool_call lines."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Call, Lead
from app.models.enums import LeadStatus
from app.services.phone import normalize_e164
from app.services.voice.booking_state import BOOKING_KEY, dump_booking, load_booking
from app.services.voice.voice_dates import parse_spoken_dates

logger = logging.getLogger(__name__)

_TOOL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S | re.I)

FILLER_TE = "ఒక్క క్షణం అండి, చూస్తున్నాను."
FILLER_EN = "One moment, let me check that for you."


def split_reply_and_tools(raw: str) -> tuple[str, list[dict]]:
    tools: list[dict] = []
    spoken = raw or ""
    for m in _TOOL_RE.finditer(raw or ""):
        try:
            tools.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
        spoken = spoken.replace(m.group(0), "")
    return spoken.strip(), tools


def _persist_lead(
    db: Session,
    call: Call,
    *,
    question: str,
    name: str | None = None,
    reason: str | None = None,
) -> Lead | None:
    workspace_id = call.workspace_id
    if not workspace_id:
        return None
    phone = str((call.captured_fields or {}).get("caller_e164") or "").strip()
    if not phone:
        return None
    try:
        e164 = normalize_e164(phone)
    except ValueError:
        e164 = phone
    row = db.scalars(
        select(Lead).where(Lead.workspace_id == workspace_id, Lead.phone_e164 == e164)
    ).first()
    if not row:
        req = question or ""
        if reason:
            req = f"[{reason}] {req}".strip()
        row = Lead(
            workspace_id=workspace_id,
            phone_e164=e164,
            name=name,
            status=LeadStatus.eligible,
            lead_source="voice_inbound",
            requirements=req[:2000],
            follow_up_required=True,
            consent_source="inbound_call",
        )
        db.add(row)
    else:
        req = (question or row.requirements or "")[:2000]
        if reason:
            req = f"[{reason}] {req}".strip()[:2000]
        row.requirements = req
        row.follow_up_required = True
        row.lead_source = row.lead_source or "voice_inbound"
    db.commit()
    db.refresh(row)
    from app.services.owner_notify import load_workspace_owner, notify_owner

    wo, contacts = load_workspace_owner(db, call.workspace_id)
    subj = f"Voice lead / callback ({row.id})"
    body = f"Phone {e164}\n{question}\nReason: {reason or 'n/a'}"
    status, ch = notify_owner(
        subject=subj, body=body, workspace_owner=wo, contacts=contacts
    )
    prof = dict(row.profile or {})
    prof["owner_notify_status"] = status if status != "skipped" else "skipped_no_channel"
    prof["owner_notify_channel"] = ch
    row.profile = prof
    db.commit()
    fields = dict(call.captured_fields or {})
    fields["lead_id"] = str(row.id)
    fields["owner_notify_status"] = prof["owner_notify_status"]
    call.captured_fields = fields
    db.commit()
    return row


def execute_tool(
    db: Session,
    call: Call,
    fields: dict,
    name: str,
    args: dict,
    *,
    caller_text: str,
    lang: str,
    tool_source: str = "llm_native",
) -> tuple[str, dict, bool]:
    """Returns (spoken_result, updated_fields, end_call)."""
    name = (name or "").strip().lower()
    args = args or {}
    t0 = time.perf_counter()
    spoken = ""
    hangup = False
    try:
        return _execute_tool_inner(
            db, call, fields, name, args, caller_text=caller_text, lang=lang, tool_source=tool_source
        )
    except Exception:
        logger.exception("tool_failed name=%s call=%s", name, getattr(call, "id", None))
        st = load_booking(fields)
        from app.services.voice.voice_booking_requests import create_voice_booking_request

        try:
            create_voice_booking_request(
                db,
                call,
                details={
                    "check_in": st.check_in,
                    "check_out": st.check_out,
                    "guests": st.guest_count,
                    "source": "voice",
                    "tool_error": name,
                },
                note=(caller_text or "")[:500],
            )
        except Exception:
            logger.exception("booking_request_fallback_failed")
        spoken = (
            "tool error అయింది కానీ మీ request note చేశాను — team confirm చేసి call చేస్తారు అండి."
            if lang == "te-IN"
            else "I hit a snag but noted your request — our team will confirm by phone."
        )
        log = list(fields.get("tool_log") or [])
        log.append({"name": name, "ok": False, "error": True, "source": tool_source, "ms": 0})
        fields["tool_log"] = log[-40:]
        return spoken, fields, False


def _execute_tool_inner(
    db: Session,
    call: Call,
    fields: dict,
    name: str,
    args: dict,
    *,
    caller_text: str,
    lang: str,
    tool_source: str,
) -> tuple[str, dict, bool]:
    spoken = ""
    hangup = False
    t0 = time.perf_counter()

    if name == "save_lead":
        q = str(args.get("question") or caller_text or "Callback requested")[:500]
        reason = str(args.get("reason") or "").strip() or None
        _persist_lead(db, call, question=q, name=args.get("name"), reason=reason)
        reason = str(args.get("reason") or "").strip()
        if reason in ("missing_fact", "unknown_amenity"):
            spoken = (
                "confirm చేసి చెప్తాము అండి — మా team మీ ప్రశ్న note చేస్తారు."
                if lang == "te-IN"
                else "We'll confirm and get back to you — I've noted your question."
            )
        else:
            spoken = (
                "నోట్ చేశాను అండి — మా team మీకు call back చేస్తారు."
                if lang == "te-IN"
                else "I've noted that — our team will call you back."
            )
    elif name == "check_availability":
        from app.services.voice.voice_booking_requests import create_voice_booking_request

        dates = parse_spoken_dates(str(args.get("dates") or caller_text))
        st = load_booking(fields)
        if dates:
            st.check_in = dates[0]
            if len(dates) > 1:
                st.check_out = dates[1]
            fields[BOOKING_KEY] = dump_booking(st)
        fields["availability_not_configured"] = True
        fields["last_tool"] = "check_availability:not_configured"
        st.availability_status = "pending"
        fields[BOOKING_KEY] = dump_booking(st)
        spoken = (
            "availability team confirm చేసి call చేస్తారు అండి — మీ request note చేశాను."
            if lang == "te-IN"
            else "Our team will confirm availability and call you back — I've noted your request."
        )
        fields["last_tool_spoken"] = spoken
    elif name == "create_booking":
        from app.services.voice.voice_booking_requests import create_voice_booking_request

        st0 = load_booking(fields)
        if (
            tool_source != "slot_flow"
            and not st0.awaiting_confirmation
            and not st0.booking_confirmed
        ):
            spoken = (
                "ముందు dates మరియు guests confirm చేసుకుందాం అండి."
                if lang == "te-IN"
                else "Let's confirm dates and guests first."
            )
            return spoken, fields, False

        confirm = bool(args.get("confirmed_verbal")) or str(args.get("confirm", "")).lower() in (
            "yes",
            "true",
            "1",
        )
        if not confirm:
            spoken = (
                "ముందు dates confirm చేసుకుందాం అండి — నిజంగా book చేయాలా?"
                if lang == "te-IN"
                else "Before I note the request — can you confirm those dates verbally?"
            )
        else:
            from app.services.voice.voice_grounding_guard import _caller_resolved_dates

            st = load_booking(fields)
            if args.get("check_in"):
                st.check_in = str(args["check_in"])
            _cin, cout_c = _caller_resolved_dates(caller_text, fields)
            if cout_c:
                st.check_out = cout_c
            else:
                st.check_out = None
            dates = parse_spoken_dates(caller_text)
            if dates and not st.check_in:
                st.check_in = dates[0]
            st.nights = st.nights or (
                (date.fromisoformat(st.check_out) - date.fromisoformat(st.check_in)).days
                if st.check_in and st.check_out
                else None
            )
            fields[BOOKING_KEY] = dump_booking(st)
            create_voice_booking_request(
                db,
                call,
                details={
                    "check_in": st.check_in,
                    "check_out": st.check_out,
                    "guests": args.get("guests") or st.guest_count,
                    "source": "voice",
                },
                note=caller_text[:500],
            )
            spoken = (
                "request note చేశాను అండి — మా team confirm చేసి call చేస్తారు."
                if lang == "te-IN"
                else "I've noted your request — our team will confirm and call you."
            )
        fields["last_tool"] = "create_booking:pending_staff"
    elif name == "transfer_to_human":
        from app.services.owner_notify import load_workspace_owner, manager_callback_minutes

        s = get_settings()
        wo, contacts = load_workspace_owner(db, call.workspace_id)
        mode = (s.voice_transfer_mode or "none").strip().lower()
        mins = manager_callback_minutes(wo, contacts, s)
        if mode == "exotel_transfer":
            num = str(args.get("number") or fields.get("transfer_number") or s.exotel_caller_id or "")
            fields["transfer_requested"] = True
            spoken = (
                f"సరే అండి, మిమ్మల్ని {num} కి connect చేస్తాను — line లోనే ఉండండి."
                if lang == "te-IN"
                else f"Connecting you to {num} — please stay on the line."
            )
            fields["last_tool"] = "transfer_to_human:exotel"
        else:
            _persist_lead(
                db,
                call,
                question=caller_text or "Wants manager",
                reason="wants_manager",
            )
            fields["transfer_requested"] = True
            if mins:
                spoken = (
                    f"మా manager మీకు {mins} నిమిషాల్లో call చేస్తారు అండి."
                    if lang == "te-IN"
                    else f"Our manager will call you back within {mins} minutes."
                )
            else:
                spoken = (
                    "మా team మీకు call చేస్తారు అండి."
                    if lang == "te-IN"
                    else "Our team will call you back."
                )
            fields["last_tool"] = "transfer_to_human:callback"
    elif name == "send_whatsapp_details":
        topic = str(args.get("topic") or "location").strip()
        fields["whatsapp_stub_topic"] = topic
        spoken = (
            "Location WhatsApp ఇంకా setup కాలేదు అండి — address note చేసి team share చేస్తారు."
            if lang == "te-IN"
            else "WhatsApp isn't configured yet — I've noted your request for our team to share details."
        )
        fields["last_tool"] = "send_whatsapp_details:not_configured"
    elif name == "end_call":
        spoken = "సరే అండి, థ్యాంక్యూ." if lang == "te-IN" else "Thank you — have a great day."
        hangup = True
        fields["last_tool"] = "end_call"

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if elapsed_ms > 700 and not spoken.startswith(FILLER_TE):
        spoken = (FILLER_TE if lang == "te-IN" else FILLER_EN) + " " + spoken

    log_tools = list(fields.get("tool_log") or [])
    log_tools.append(
        {
            "name": name,
            "args": args,
            "elapsed_ms": round(elapsed_ms, 1),
            "source": tool_source,
        }
    )
    fields["tool_log"] = log_tools[-20:]
    return spoken, fields, hangup