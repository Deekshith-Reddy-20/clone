"""Outpero inbound call.ended → Calls screen.

Persists post-call transcript/summary when present on the webhook or an authorized
status poll. Does not create/update leads or mark bookings complete. Never overwrites
a stored transcript with empty on replay. Never logs transcript bodies.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Call
from app.models.enums import CallDirection, CallOutcome
from app.models.outpero import OutperoInboundConnection, OutperoSyncLog, OutperoWebhookEvent
from app.services.outpero.sync import format_transcript, map_outpero_status_to_outcome, parse_timestamp

logger = logging.getLogger(__name__)

ALLOWED_EVENTS = frozenset({"call.ended"})
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def inbound_import_enabled(settings=None) -> bool:
    settings = settings or get_settings()
    deployment = (settings.karyuk_deployment or settings.app_env or "").strip().lower()
    if deployment in {"production", "prod"}:
        return False
    return bool(settings.outpero_inbound_import_enabled)


def resolve_inbound_connection(db: Session, connection_key: str) -> OutperoInboundConnection | None:
    return db.execute(
        select(OutperoInboundConnection).where(
            OutperoInboundConnection.connection_key == connection_key
        )
    ).scalar_one_or_none()


def connection_signing_secret(connection: OutperoInboundConnection, settings=None) -> str:
    settings = settings or get_settings()
    return (
        (connection.signing_secret or "").strip()
        or (settings.outpero_inbound_webhook_secret or "").strip()
        or (settings.outpero_webhook_shared_secret or "").strip()
    )


def _normalize_e164(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().replace(" ", "")
    if not raw:
        return None
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not raw.startswith("+") and raw.isdigit():
        raw = "+" + raw
    return raw if _E164_RE.match(raw) else raw


def resolve_inbound_caller_legs(
    payload: dict[str, Any],
    connection: OutperoInboundConnection,
) -> tuple[str | None, str | None]:
    """Return (caller_e164, route_e164) for inbound Outpero payloads.

    Live Outpero often puts the bound DID on ``from_number`` and the remote party
    on ``to_number``. Prefer ``customer_number`` / ``business_number`` when present.
    """
    flat = flatten_outpero_payload(payload)
    did = _normalize_e164(connection.did_e164)
    business = _normalize_e164(flat.get("business_number")) or did
    customer = _normalize_e164(flat.get("customer_number") or flat.get("phone"))
    raw_from = _normalize_e164(flat.get("from_number") or flat.get("from"))
    raw_to = _normalize_e164(flat.get("to_number") or flat.get("to"))
    direction = str(flat.get("direction") or "inbound").strip().lower()
    if direction != "inbound":
        return raw_from, raw_to or business

    if customer:
        return customer, business or did or raw_to
    if did and raw_from and raw_from == did and raw_to and raw_to != did:
        return raw_to, did
    if did and not raw_from and raw_to and raw_to != did:
        return raw_to, did
    return raw_from, raw_to or did


def _merge_inbound_captured(prev: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Merge captured meta without wiping caller/route legs with empty replay values."""
    out = {**prev, **meta}
    for key in ("from_number", "to_number", "hangup_reason"):
        if meta.get(key) is None and prev.get(key) is not None:
            out[key] = prev[key]
    return out


def validate_binding(connection: OutperoInboundConnection, payload: dict[str, Any]) -> str | None:
    """Return deny reason or None when payload matches the server-side binding."""
    payload = flatten_outpero_payload(payload)
    event = str(payload.get("event") or "").strip()
    if event not in ALLOWED_EVENTS:
        return "unsupported_event"

    employee = str(payload.get("employee") or payload.get("slug") or "").strip()
    if employee and employee != connection.employee_slug:
        # Live Outpero often puts display name ("Harish") or employee UUID in
        # `employee`. Only reject another slug-shaped id (no spaces).
        employee_id = str(payload.get("employee_id") or "").strip()
        uuid_like = bool(re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", employee))
        display_like = (" " in employee) or (not re.search(r"[0-9]", employee) and len(employee) <= 64)
        if employee == employee_id or uuid_like or display_like:
            pass
        else:
            return "employee_mismatch"

    # Destination / DID: prefer `to` for inbound answered-on-our-number.
    # Live Outpero has also been observed to put the bound DID on `from_number`
    # and the remote party on `to_number` for inbound call.ended — accept either leg.
    candidates = [
        payload.get("to_number"),
        payload.get("to"),
        payload.get("destination"),
        payload.get("did"),
        payload.get("from_number"),
        payload.get("from"),
    ]
    direction = str(payload.get("direction") or "inbound").strip().lower()
    if direction == "inbound":
        matched = False
        expected = _normalize_e164(connection.did_e164)
        for cand in candidates:
            got = _normalize_e164(cand)
            if got and expected and got == expected:
                matched = True
                break
        # Allow missing destination on Test Send fixtures that omit numbers
        if any(candidates) and not matched:
            return "did_mismatch"
    return None


def flatten_outpero_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Nested field-shape into the flat keys Phase-1 expects."""
    flat = dict(payload)
    call = payload.get("call")
    if isinstance(call, dict):
        for src, dest in (
            ("id", "call_id"),
            ("call_id", "call_id"),
            ("status", "status"),
            ("direction", "direction"),
            ("from", "from_number"),
            ("from_number", "from_number"),
            ("to", "to_number"),
            ("to_number", "to_number"),
            ("duration_s", "duration_s"),
            ("duration_seconds", "duration_seconds"),
            ("started_at", "started_at"),
            ("ended_at", "ended_at"),
            ("hangup_reason", "hangup_reason"),
            ("transcript", "transcript"),
            ("summary", "summary"),
            ("outcome", "outcome"),
            ("recording_url", "recording_url"),
        ):
            if dest not in flat and call.get(src) is not None:
                flat[dest] = call[src]
    # Nested conversation shapes used by some Outpero deliveries.
    for alt in ("conversation", "messages", "turns", "utterances"):
        if "transcript" not in flat and isinstance(payload.get(alt), list):
            flat["transcript"] = payload[alt]
    employee = payload.get("employee")
    if isinstance(employee, dict):
        slug = employee.get("slug") or employee.get("id") or employee.get("name")
        if slug and "employee" not in flat:
            flat["employee"] = slug
        elif slug:
            flat["employee"] = slug
    elif employee is not None:
        flat["employee"] = employee
    return flat


def allowlisted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize inbound fields. Transcript/summary kept when present; captured blob dropped."""
    payload = flatten_outpero_payload(payload)
    keys = (
        "event",
        "call_id",
        "status",
        "direction",
        "employee",
        "slug",
        "from_number",
        "from",
        "to_number",
        "to",
        "destination",
        "did",
        "duration_s",
        "duration_seconds",
        "started_at",
        "ended_at",
        "hangup_reason",
        "karyuk_test",
        "transcript",
        "summary",
        "outcome",
    )
    out: dict[str, Any] = {}
    for key in keys:
        if key in payload and payload[key] is not None:
            out[key] = payload[key]
    return out


def apply_post_call_transcript_fields(call: Call, payload: dict[str, Any]) -> dict[str, bool]:
    """Apply non-empty transcript/summary/disposition. Never wipe existing with empty."""
    flat = flatten_outpero_payload(payload)
    transcript = format_transcript(flat.get("transcript"))
    summary = flat.get("summary") if isinstance(flat.get("summary"), str) else None
    if isinstance(summary, str):
        summary = summary.strip() or None
    disposition = flat.get("outcome") if isinstance(flat.get("outcome"), str) else None
    if isinstance(disposition, str):
        disposition = disposition.strip() or None

    applied = {"transcript": False, "summary": False, "disposition": False}
    if transcript:
        call.transcript = transcript
        applied["transcript"] = True
    if summary:
        call.summary = summary
        applied["summary"] = True
    if disposition:
        call.disposition = disposition
        applied["disposition"] = True

    meta = dict(call.captured_fields or {})
    if applied["transcript"]:
        meta["transcript_excluded"] = False
        meta["transcript_source"] = str(flat.get("event") or "outpero_post_call")
    elif "transcript_excluded" not in meta:
        meta["transcript_excluded"] = call.transcript is None
    if applied["summary"]:
        meta["summary_excluded"] = False
    call.captured_fields = meta
    return applied


def upsert_inbound_call_metadata(
    db: Session,
    *,
    workspace_id: UUID,
    payload: dict[str, Any],
    connection: OutperoInboundConnection,
    is_test: bool = False,
) -> Call:
    safe = allowlisted_payload(payload)
    external_call_id = str(safe.get("call_id") or "").strip() or None

    def _find_call() -> Call | None:
        if not external_call_id:
            return None
        # first() — concurrent deliveries can briefly create duplicates before dedupe.
        return (
            db.execute(
                select(Call)
                .where(
                    Call.workspace_id == workspace_id,
                    Call.provider == "outpero",
                    Call.provider_call_sid == external_call_id,
                )
                .order_by(Call.created_at.asc())
            )
            .scalars()
            .first()
        )

    call = _find_call()

    direction_raw = str(safe.get("direction") or "inbound").strip().lower()
    direction = CallDirection.inbound if direction_raw != "outbound" else CallDirection.outbound
    outcome = map_outpero_status_to_outcome(
        str(safe.get("status")) if safe.get("status") is not None else None,
        str(safe.get("hangup_reason")) if safe.get("hangup_reason") is not None else None,
    )
    duration = int(safe.get("duration_s") or safe.get("duration_seconds") or 0)
    started_at = parse_timestamp(safe.get("started_at"))
    ended_at = parse_timestamp(safe.get("ended_at"))
    transcript = format_transcript(safe.get("transcript"))
    summary = safe.get("summary") if isinstance(safe.get("summary"), str) else None
    if isinstance(summary, str):
        summary = summary.strip() or None
    disposition = safe.get("outcome") if isinstance(safe.get("outcome"), str) else None
    if isinstance(disposition, str):
        disposition = disposition.strip() or None

    caller_number, route_number = resolve_inbound_caller_legs(payload, connection)
    meta = {
        "phase": "inbound_call_import_v1",
        "connection_key": connection.connection_key,
        "from_number": caller_number,
        "to_number": route_number or connection.did_e164,
        "employee": safe.get("employee") or connection.employee_slug,
        "hangup_reason": safe.get("hangup_reason"),
        "is_test": is_test,
        "transcript_excluded": transcript is None,
        "recording_excluded": True,
        "summary_excluded": summary is None,
        "captured_excluded": True,
    }
    terminal = {
        CallOutcome.completed,
        CallOutcome.no_answer,
        CallOutcome.busy,
        CallOutcome.failed,
        CallOutcome.canceled,
    }

    if call is None:
        call = Call(
            workspace_id=workspace_id,
            lead_id=None,
            outpero_agent_id=connection.outpero_agent_id,
            direction=direction,
            outcome=outcome,
            duration_seconds=duration,
            transcript=transcript,
            summary=summary,
            captured_fields=meta,
            provider="outpero",
            provider_call_sid=external_call_id,
            recording_url=None,
            disposition=disposition,
            started_at=started_at,
            ended_at=ended_at,
            is_test=is_test,
            finalized_at=(ended_at or datetime.now(UTC)) if outcome in terminal else None,
        )
        db.add(call)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            call = _find_call()
            if call is None:
                raise
            # Duplicate create race: merge onto the surviving row without wiping transcript.
            call.direction = direction
            call.outcome = outcome
            if duration:
                call.duration_seconds = duration
            if started_at:
                call.started_at = started_at
            if ended_at:
                call.ended_at = ended_at
            prev = dict(call.captured_fields or {})
            for sensitive in ("transcript", "recording_url", "summary", "captured", "pre_call"):
                prev.pop(sensitive, None)
            call.captured_fields = _merge_inbound_captured(prev, meta)
            apply_post_call_transcript_fields(call, safe)
            if connection.outpero_agent_id:
                call.outpero_agent_id = connection.outpero_agent_id
            call.is_test = call.is_test or is_test
            if outcome in terminal:
                call.finalized_at = ended_at or call.finalized_at or datetime.now(UTC)
            db.flush()
    else:
        call.direction = direction
        call.outcome = outcome
        if duration:
            call.duration_seconds = duration
        if started_at:
            call.started_at = started_at
        if ended_at:
            call.ended_at = ended_at
        # Never wipe an existing transcript/summary with empty on replay.
        prev = dict(call.captured_fields or {})
        for sensitive in ("transcript", "recording_url", "summary", "captured", "pre_call"):
            prev.pop(sensitive, None)
        # Preserve prior availability of transcript when this delivery omitted it.
        if transcript is None and call.transcript:
            meta["transcript_excluded"] = False
        if summary is None and call.summary:
            meta["summary_excluded"] = False
        call.captured_fields = _merge_inbound_captured(prev, meta)
        apply_post_call_transcript_fields(call, safe)
        if connection.outpero_agent_id:
            call.outpero_agent_id = connection.outpero_agent_id
        call.is_test = call.is_test or is_test
        if outcome in terminal:
            call.finalized_at = ended_at or call.finalized_at or datetime.now(UTC)
        db.flush()

    return call


def recover_inbound_transcript_from_provider(
    db: Session,
    *,
    call: Call,
    connection: OutperoInboundConnection,
    client: Any | None = None,
) -> dict[str, Any]:
    """Fill transcript/summary from authorized GET /lead-intake/.../calls/{id} only.

    Does not create leads, change DID/webhook, or log transcript text.
    """
    from app.models.outpero import OutperoAgent
    from app.services.outpero.client import OutperoApiError, OutperoClient

    if call.workspace_id != connection.workspace_id:
        return {"ok": False, "reason": "workspace_mismatch"}
    if not call.provider_call_sid:
        return {"ok": False, "reason": "missing_provider_call_sid"}
    agent = db.get(OutperoAgent, connection.outpero_agent_id) if connection.outpero_agent_id else None
    if agent is None or not agent.lead_secret or not agent.slug:
        return {"ok": False, "reason": "agent_credentials_unavailable"}

    client = client or OutperoClient()
    try:
        payload = client.get_call(
            slug=agent.slug,
            lead_secret=agent.lead_secret,
            call_id=call.provider_call_sid,
        )
    except OutperoApiError as exc:
        logger.warning(
            "outpero_transcript_recover_failed call_id=%s status=%s",
            call.id,
            getattr(exc, "status_code", None),
        )
        return {"ok": False, "reason": "provider_error"}

    if not isinstance(payload, dict):
        return {"ok": False, "reason": "invalid_provider_payload"}

    before_t = bool(call.transcript)
    before_s = bool(call.summary)
    applied = apply_post_call_transcript_fields(call, payload)
    # Restore caller/route from authorized provider fields when webhook/replay
    # left the DID on from_number or wiped the remote leg.
    caller_number, route_number = resolve_inbound_caller_legs(payload, connection)
    meta = dict(call.captured_fields or {})
    did = _normalize_e164(connection.did_e164)
    current_from = _normalize_e164(meta.get("from_number"))
    legs_applied = False
    if caller_number and (not current_from or (did and current_from == did)):
        meta["from_number"] = caller_number
        if route_number:
            meta["to_number"] = route_number
        call.captured_fields = meta
        legs_applied = True
    db.add(call)
    db.commit()
    db.refresh(call)
    return {
        "ok": True,
        "call_id": str(call.id),
        "provider_call_sid": call.provider_call_sid,
        "applied": applied,
        "legs_applied": legs_applied,
        "had_transcript_before": before_t,
        "had_summary_before": before_s,
        "has_transcript": bool(call.transcript),
        "has_summary": bool(call.summary),
        "transcript_turns": len(call.transcript.splitlines()) if call.transcript else 0,
    }


def process_inbound_call_ended(
    db: Session,
    *,
    connection: OutperoInboundConnection,
    payload: dict[str, Any],
    event_row: OutperoWebhookEvent | None,
    is_test: bool = False,
) -> dict[str, Any]:
    # Claim the durable event so concurrent workers skip once processed.
    if event_row is not None:
        locked = db.execute(
            select(OutperoWebhookEvent)
            .where(OutperoWebhookEvent.id == event_row.id)
            .with_for_update()
        ).scalar_one_or_none()
        if locked is None:
            return {"skipped": True, "reason": "event_missing"}
        if locked.status == "processed":
            return {
                "call_id": locked.call_id,
                "provider_call_sid": locked.external_call_id,
                "duplicate": True,
                "phase": "inbound_call_import_v1",
            }
        event_row = locked

    call = upsert_inbound_call_metadata(
        db,
        workspace_id=connection.workspace_id,
        payload=payload,
        connection=connection,
        is_test=is_test,
    )
    if event_row:
        event_row.status = "processed"
        event_row.call_id = call.id
        event_row.processed_at = datetime.now(UTC)
        event_row.external_call_id = call.provider_call_sid
        event_row.payload = allowlisted_payload(payload)

    db.add(
        OutperoSyncLog(
            workspace_id=connection.workspace_id,
            outpero_agent_id=connection.outpero_agent_id,
            operation="webhook.inbound.call.ended",
            status="ok",
            detail=f"Phase-1 inbound call {call.provider_call_sid or call.id}",
            meta={
                "call_id": str(call.id),
                "connection_key": connection.connection_key,
                "external_call_id": call.provider_call_sid,
                "lead_id": None,
            },
        )
    )
    db.commit()
    db.refresh(call)
    return {
        "call_id": call.id,
        "provider_call_sid": call.provider_call_sid,
        "outcome": call.outcome.value if hasattr(call.outcome, "value") else call.outcome,
        "phase": "inbound_call_import_v1",
    }


def durable_event_key(connection_key: str, payload: dict[str, Any]) -> str:
    """Deduplicate by provider connection + call_id (Phase-1 requirement)."""
    call_id = str(payload.get("call_id") or payload.get("id") or "unknown")
    return f"inbound:{connection_key}:{call_id}"[:191]
