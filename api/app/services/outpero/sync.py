"""Synchronize Outpero call.ended payloads into Karyuk leads + calls."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Call, Lead
from app.models.enums import CallDirection, CallOutcome, LeadStatus
from app.models.outpero import OutperoAgent, OutperoSyncLog, OutperoWebhookEvent
from app.services.audit import log_audit
from app.services.phone import normalize_e164

logger = logging.getLogger(__name__)

QUALIFICATION_MAP = {
    "interested": "interested",
    "qualified": "qualified",
    "not_interested": "not_interested",
    "unqualified": "unqualified",
    "follow_up": "follow_up_required",
    "follow_up_required": "follow_up_required",
    "callback": "follow_up_required",
    "voicemail": "follow_up_required",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def format_transcript(transcript: Any) -> str | None:
    if transcript is None:
        return None
    if isinstance(transcript, str):
        return transcript.strip() or None
    if isinstance(transcript, list):
        lines: list[str] = []
        for turn in transcript:
            if isinstance(turn, str):
                lines.append(turn)
                continue
            if not isinstance(turn, dict):
                continue
            role = (
                turn.get("role")
                or turn.get("speaker")
                or turn.get("from")
                or turn.get("name")
                or "speaker"
            )
            text = turn.get("text") or turn.get("content") or turn.get("message") or ""
            if text:
                lines.append(f"{role}: {text}")
        return "\n".join(lines) if lines else None
    return str(transcript)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def map_outpero_status_to_outcome(status: str | None, hangup_reason: str | None = None) -> CallOutcome:
    normalized = (status or "").strip().lower()
    reason = (hangup_reason or "").strip().lower()
    if normalized in {"completed", "complete", "done"}:
        return CallOutcome.completed
    if normalized in {"voicemail"}:
        return CallOutcome.completed
    if normalized in {"no_answer", "no-answer", "unanswered"}:
        return CallOutcome.no_answer
    if normalized in {"busy"}:
        return CallOutcome.busy
    if normalized in {"failed", "error"}:
        return CallOutcome.failed
    if normalized in {"canceled", "cancelled"}:
        return CallOutcome.canceled
    if "busy" in reason:
        return CallOutcome.busy
    if "no_answer" in reason or "no-answer" in reason:
        return CallOutcome.no_answer
    if normalized in {"ringing"}:
        return CallOutcome.ringing
    if normalized in {"dialing", "queued", "accepted"}:
        return CallOutcome.dialing
    if normalized in {"connected", "in_progress", "in-progress"}:
        return CallOutcome.connected
    return CallOutcome.completed if normalized else CallOutcome.queued


def extract_phone(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("to_number"),
        payload.get("to"),
        payload.get("phone"),
        payload.get("customer_phone"),
        _as_dict(payload.get("pre_call")).get("phone"),
        payload.get("from_number") if (payload.get("direction") or "").lower() == "inbound" else None,
    ]
    for raw in candidates:
        if not raw or not isinstance(raw, str):
            continue
        try:
            return normalize_e164(raw)
        except ValueError:
            continue
    return None


def extract_lead_name(payload: dict[str, Any], captured: dict[str, Any], pre_call: dict[str, Any]) -> str | None:
    for source in (captured, pre_call, payload):
        for key in ("lead_name", "name", "full_name", "customer_name"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:255]
    return None


def derive_qualification(outcome: str | None, captured: dict[str, Any]) -> str | None:
    if isinstance(captured.get("qualification"), str) and captured["qualification"].strip():
        return captured["qualification"].strip()[:64]
    if outcome:
        mapped = QUALIFICATION_MAP.get(outcome.strip().lower())
        if mapped:
            return mapped
    return None


def _merge_preserve(existing: str | None, incoming: str | None) -> str | None:
    if incoming is None or (isinstance(incoming, str) and not incoming.strip()):
        return existing
    return incoming.strip() if isinstance(incoming, str) else existing


def upsert_lead_from_outpero(
    db: Session,
    *,
    workspace_id: UUID,
    payload: dict[str, Any],
    agent: OutperoAgent | None,
    is_test: bool = False,
) -> Lead | None:
    phone = extract_phone(payload)
    if not phone:
        logger.warning("outpero_lead_missing_phone workspace=%s", workspace_id)
        return None

    captured = _as_dict(payload.get("captured"))
    pre_call = _as_dict(payload.get("pre_call"))
    outcome = payload.get("outcome")
    if isinstance(outcome, str):
        outcome_norm = outcome.strip().lower()
    else:
        outcome_norm = None

    lead = db.execute(
        select(Lead).where(Lead.workspace_id == workspace_id, Lead.phone_e164 == phone)
    ).scalar_one_or_none()

    name = extract_lead_name(payload, captured, pre_call)
    email = _merge_preserve(
        getattr(lead, "email", None) if lead else None,
        captured.get("email") or pre_call.get("email") or payload.get("email"),
    )
    company = _merge_preserve(
        getattr(lead, "company", None) if lead else None,
        captured.get("company") or pre_call.get("company"),
    )
    location = _merge_preserve(
        getattr(lead, "location", None) if lead else None,
        captured.get("location")
        or captured.get("city")
        or pre_call.get("location")
        or pre_call.get("city"),
    )
    requirements = _merge_preserve(
        getattr(lead, "requirements", None) if lead else None,
        captured.get("requirements")
        or captured.get("interest")
        or pre_call.get("interest")
        or pre_call.get("requirements"),
    )
    budget = _merge_preserve(
        getattr(lead, "budget", None) if lead else None,
        captured.get("budget") or pre_call.get("budget"),
    )
    interest_level = _merge_preserve(
        getattr(lead, "interest_level", None) if lead else None,
        captured.get("interest_level") or captured.get("interest") or outcome_norm,
    )
    qualification = derive_qualification(outcome_norm, captured)
    follow_up_required = bool(
        captured.get("follow_up_required")
        or (qualification == "follow_up_required")
        or outcome_norm in {"follow_up", "callback", "voicemail"}
    )
    next_follow_up = parse_timestamp(
        captured.get("next_follow_up_at")
        or captured.get("follow_up_at")
        or captured.get("visit")
        or captured.get("callback_at")
    )

    profile_extra = {
        k: v
        for k, v in {**pre_call, **captured}.items()
        if k
        not in {
            "phone",
            "name",
            "lead_name",
            "full_name",
            "email",
            "company",
            "location",
            "city",
            "budget",
            "requirements",
            "interest",
            "interest_level",
            "qualification",
            "follow_up_required",
            "next_follow_up_at",
            "follow_up_at",
        }
    }

    now = datetime.now(UTC)
    if lead is None:
        lead = Lead(
            workspace_id=workspace_id,
            name=name,
            phone_e164=phone,
            status=LeadStatus.eligible,
            consent_source="outpero_test" if is_test else "outpero",
            email=email,
            company=company,
            location=location,
            lead_source="outpero",
            qualification=qualification,
            interest_level=interest_level,
            requirements=requirements,
            budget=budget,
            follow_up_required=follow_up_required,
            next_follow_up_at=next_follow_up,
            profile={
                "outpero_agent_id": str(agent.id) if agent else None,
                "outpero_agent_name": agent.name if agent else None,
                "custom": profile_extra,
            },
            last_interaction_at=now,
        )
        db.add(lead)
        db.flush()
        return lead

    # Preserve existing values when Outpero omits a field
    if name and not lead.name:
        lead.name = name
    elif name:
        lead.name = name
    lead.email = _merge_preserve(lead.email, email)
    lead.company = _merge_preserve(lead.company, company)
    lead.location = _merge_preserve(lead.location, location)
    lead.requirements = _merge_preserve(lead.requirements, requirements)
    lead.budget = _merge_preserve(lead.budget, budget)
    lead.interest_level = _merge_preserve(lead.interest_level, interest_level)
    if qualification:
        lead.qualification = qualification
    if follow_up_required:
        lead.follow_up_required = True
    if next_follow_up:
        lead.next_follow_up_at = next_follow_up
    if not lead.lead_source:
        lead.lead_source = "outpero"
    profile = dict(lead.profile or {})
    custom = dict(profile.get("custom") or {})
    custom.update({k: v for k, v in profile_extra.items() if v is not None})
    profile["custom"] = custom
    if agent:
        profile["outpero_agent_id"] = str(agent.id)
        profile["outpero_agent_name"] = agent.name
    lead.profile = profile
    lead.last_interaction_at = now
    lead.updated_at = now
    db.flush()
    return lead


def upsert_call_from_outpero(
    db: Session,
    *,
    workspace_id: UUID,
    payload: dict[str, Any],
    agent: OutperoAgent | None,
    lead: Lead | None,
    is_test: bool = False,
) -> Call:
    external_call_id = str(payload.get("call_id") or payload.get("id") or "").strip() or None
    call: Call | None = None
    if external_call_id:
        call = db.execute(
            select(Call).where(
                Call.workspace_id == workspace_id,
                Call.provider == "outpero",
                Call.provider_call_sid == external_call_id,
            )
        ).scalar_one_or_none()

    direction_raw = (payload.get("direction") or "outbound").strip().lower()
    direction = CallDirection.inbound if direction_raw == "inbound" else CallDirection.outbound
    outcome = map_outpero_status_to_outcome(
        str(payload.get("status") or "") if payload.get("status") is not None else None,
        str(payload.get("hangup_reason") or "") if payload.get("hangup_reason") is not None else None,
    )
    duration = int(payload.get("duration_s") or payload.get("duration_seconds") or 0)
    captured = _as_dict(payload.get("captured"))
    pre_call = _as_dict(payload.get("pre_call"))
    transcript = format_transcript(payload.get("transcript"))
    summary = payload.get("summary") if isinstance(payload.get("summary"), str) else None
    recording_url = payload.get("recording_url") if isinstance(payload.get("recording_url"), str) else None
    disposition = payload.get("outcome") if isinstance(payload.get("outcome"), str) else None
    started_at = parse_timestamp(payload.get("started_at"))
    ended_at = parse_timestamp(payload.get("ended_at"))

    captured_fields = {
        "pre_call": pre_call,
        "captured": captured,
        "hangup_reason": payload.get("hangup_reason"),
        "from_number": payload.get("from_number") or payload.get("from"),
        "to_number": payload.get("to_number") or payload.get("to"),
        "employee": payload.get("employee"),
        "event": payload.get("event") or "call.ended",
        "is_test": is_test,
    }

    if call is None:
        call = Call(
            workspace_id=workspace_id,
            lead_id=lead.id if lead else None,
            outpero_agent_id=agent.id if agent else None,
            direction=direction,
            outcome=outcome,
            duration_seconds=duration,
            transcript=transcript,
            summary=summary,
            captured_fields=captured_fields,
            provider="outpero",
            provider_call_sid=external_call_id,
            recording_url=recording_url,
            disposition=disposition,
            started_at=started_at,
            ended_at=ended_at,
            is_test=is_test,
            finalized_at=ended_at or datetime.now(UTC)
            if outcome
            in {
                CallOutcome.completed,
                CallOutcome.no_answer,
                CallOutcome.busy,
                CallOutcome.failed,
                CallOutcome.canceled,
            }
            else None,
        )
        db.add(call)
    else:
        # Prefer richer later payloads; never wipe existing transcript/summary with empty
        call.direction = direction
        call.outcome = outcome
        if duration:
            call.duration_seconds = duration
        if transcript:
            call.transcript = transcript
        if summary:
            call.summary = summary
        call.captured_fields = {**(call.captured_fields or {}), **captured_fields}
        if recording_url:
            call.recording_url = recording_url
        if disposition:
            call.disposition = disposition
        if started_at:
            call.started_at = started_at
        if ended_at:
            call.ended_at = ended_at
        if lead and not call.lead_id:
            call.lead_id = lead.id
        if agent:
            call.outpero_agent_id = agent.id
        call.is_test = call.is_test or is_test
        if outcome in {
            CallOutcome.completed,
            CallOutcome.no_answer,
            CallOutcome.busy,
            CallOutcome.failed,
            CallOutcome.canceled,
        }:
            call.finalized_at = ended_at or call.finalized_at or datetime.now(UTC)

    db.flush()
    return call


def process_call_ended_payload(
    db: Session,
    *,
    workspace_id: UUID,
    payload: dict[str, Any],
    agent: OutperoAgent | None,
    event_row: OutperoWebhookEvent | None = None,
    is_test: bool = False,
    actor_user_id: UUID | None = None,
) -> dict[str, Any]:
    lead = upsert_lead_from_outpero(
        db,
        workspace_id=workspace_id,
        payload=payload,
        agent=agent,
        is_test=is_test,
    )
    call = upsert_call_from_outpero(
        db,
        workspace_id=workspace_id,
        payload=payload,
        agent=agent,
        lead=lead,
        is_test=is_test,
    )
    if agent:
        agent.last_activity_at = datetime.now(UTC)

    if event_row:
        event_row.status = "processed"
        event_row.call_id = call.id
        event_row.processed_at = datetime.now(UTC)
        event_row.external_call_id = call.provider_call_sid

    db.add(
        OutperoSyncLog(
            workspace_id=workspace_id,
            outpero_agent_id=agent.id if agent else None,
            operation="webhook.call.ended",
            status="ok",
            detail=f"Synced call {call.provider_call_sid or call.id}",
            meta={
                "call_id": str(call.id),
                "lead_id": str(lead.id) if lead else None,
                "external_call_id": call.provider_call_sid,
            },
        )
    )
    log_audit(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="outpero.call.synced",
        summary=f"Outpero call synced ({call.provider_call_sid or call.id})",
    )
    db.commit()
    db.refresh(call)
    if lead:
        db.refresh(lead)
    return {
        "call_id": call.id,
        "lead_id": lead.id if lead else None,
        "provider_call_sid": call.provider_call_sid,
        "outcome": call.outcome.value if hasattr(call.outcome, "value") else call.outcome,
        "disposition": call.disposition,
    }


def build_event_key(payload: dict[str, Any]) -> str:
    call_id = str(payload.get("call_id") or payload.get("id") or "unknown")
    event = str(payload.get("event") or "call.ended")
    ended = str(payload.get("ended_at") or payload.get("duration_s") or "")
    return f"{event}:{call_id}:{ended}"[:191]
