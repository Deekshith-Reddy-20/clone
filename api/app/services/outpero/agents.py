"""Outpero agent registry and call orchestration helpers."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Call, Lead
from app.models.enums import CallDirection, CallOutcome, LeadStatus
from app.models.outpero import OutperoAgent, OutperoSyncLog
from app.services.outpero.client import OutperoApiError, OutperoClient
from app.services.outpero.signatures import mask_secret
from app.services.outpero.sync import process_call_ended_payload
from app.services.phone import normalize_e164

logger = logging.getLogger(__name__)


def serialize_agent(agent: OutperoAgent, *, stats: dict[str, int] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": agent.id,
        "name": agent.name,
        "slug": agent.slug,
        "status": agent.status,
        "lead_secret_masked": mask_secret(agent.lead_secret),
        "webhook_signing_configured": bool(agent.webhook_signing_secret),
        "action_secret_masked": mask_secret(agent.action_secret),
        "schema_cache": agent.schema_cache or {},
        "config": agent.config or {},
        "last_activity_at": agent.last_activity_at,
        "last_schema_synced_at": agent.last_schema_synced_at,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "capabilities": {
            "submit_lead_and_call": True,
            "get_schema": True,
            "get_call_status": True,
            "receive_post_call_webhook": True,
            "list_agents_via_api": False,
            "update_agent_settings_via_api": False,
            "activate_deactivate_via_api": False,
            "browser_voice_test": False,
            "list_call_history_via_api": False,
        },
    }
    if stats is not None:
        data.update(stats)
    return data


def agent_stats(db: Session, agent: OutperoAgent) -> dict[str, int]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(Call)
            .where(Call.outpero_agent_id == agent.id, Call.provider == "outpero")
        )
        or 0
    )
    successful = (
        db.scalar(
            select(func.count())
            .select_from(Call)
            .where(
                Call.outpero_agent_id == agent.id,
                Call.provider == "outpero",
                Call.outcome == CallOutcome.completed,
            )
        )
        or 0
    )
    failed = (
        db.scalar(
            select(func.count())
            .select_from(Call)
            .where(
                Call.outpero_agent_id == agent.id,
                Call.provider == "outpero",
                Call.outcome.in_([CallOutcome.failed, CallOutcome.busy, CallOutcome.no_answer, CallOutcome.canceled]),
            )
        )
        or 0
    )
    leads_generated = (
        db.scalar(
            select(func.count(func.distinct(Call.lead_id)))
            .select_from(Call)
            .where(
                Call.outpero_agent_id == agent.id,
                Call.provider == "outpero",
                Call.lead_id.is_not(None),
            )
        )
        or 0
    )
    return {
        "total_calls": int(total),
        "successful_calls": int(successful),
        "failed_calls": int(failed),
        "leads_generated": int(leads_generated),
    }


def get_agent(db: Session, workspace_id: UUID, agent_id: UUID) -> OutperoAgent | None:
    agent = db.get(OutperoAgent, agent_id)
    if not agent or agent.workspace_id != workspace_id:
        return None
    return agent


def get_active_agent(db: Session, workspace_id: UUID) -> OutperoAgent | None:
    return db.scalars(
        select(OutperoAgent)
        .where(
            OutperoAgent.workspace_id == workspace_id,
            OutperoAgent.status == "active",
        )
        .order_by(OutperoAgent.created_at.asc())
    ).first()


def ensure_env_agent(db: Session, workspace_id: UUID | None = None) -> OutperoAgent | None:
    """Create/update the default voice agent from OUTPERO_DEFAULT_* env vars."""
    from app.config import get_settings
    from app.models import Workspace

    settings = get_settings()
    slug = (settings.outpero_default_slug or "").strip()
    secret = (settings.outpero_default_lead_secret or "").strip()
    if not slug or not secret:
        return None

    ws_id = workspace_id
    if ws_id is None:
        configured = (settings.outpero_default_workspace_id or "").strip()
        if configured:
            try:
                ws_id = UUID(configured)
            except ValueError:
                ws_id = None
        if ws_id is None:
            ws = db.scalars(select(Workspace).order_by(Workspace.created_at.asc())).first()
            if not ws:
                return None
            ws_id = ws.id

    agent = db.execute(
        select(OutperoAgent).where(OutperoAgent.workspace_id == ws_id, OutperoAgent.slug == slug)
    ).scalar_one_or_none()
    webhook_secret = (settings.outpero_default_webhook_secret or "").strip() or None
    name = (settings.outpero_default_name or "Primary voice agent").strip()
    if agent is None:
        agent = OutperoAgent(
            workspace_id=ws_id,
            name=name,
            slug=slug,
            lead_secret=secret,
            webhook_signing_secret=webhook_secret,
            action_secret=secrets.token_urlsafe(24),
            status="active",
            schema_cache={},
            config={"bootstrapped_from_env": True},
        )
        db.add(agent)
    else:
        agent.name = name
        agent.lead_secret = secret
        if webhook_secret is not None:
            agent.webhook_signing_secret = webhook_secret
        agent.status = "active"
        agent.config = {**(agent.config or {}), "bootstrapped_from_env": True}
        agent.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(agent)
    return agent


def create_agent(
    db: Session,
    *,
    workspace_id: UUID,
    name: str,
    slug: str,
    lead_secret: str,
    webhook_signing_secret: str | None = None,
    config: dict[str, Any] | None = None,
) -> OutperoAgent:
    agent = OutperoAgent(
        workspace_id=workspace_id,
        name=name.strip(),
        slug=slug.strip(),
        lead_secret=lead_secret.strip(),
        webhook_signing_secret=(webhook_signing_secret or "").strip() or None,
        action_secret=secrets.token_urlsafe(24),
        status="active",
        config=config or {},
        schema_cache={},
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def update_agent(
    db: Session,
    agent: OutperoAgent,
    *,
    name: str | None = None,
    lead_secret: str | None = None,
    webhook_signing_secret: str | None = None,
    status: str | None = None,
    config: dict[str, Any] | None = None,
) -> OutperoAgent:
    if name is not None:
        agent.name = name.strip()
    if lead_secret is not None and lead_secret.strip():
        agent.lead_secret = lead_secret.strip()
    if webhook_signing_secret is not None:
        agent.webhook_signing_secret = webhook_signing_secret.strip() or None
    if status is not None:
        if status not in {"active", "inactive"}:
            raise ValueError("status must be active or inactive")
        agent.status = status
    if config is not None:
        agent.config = {**(agent.config or {}), **config}
    agent.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(agent)
    return agent


def refresh_schema(db: Session, agent: OutperoAgent, client: OutperoClient | None = None) -> dict[str, Any]:
    client = client or OutperoClient()
    schema = client.get_schema(slug=agent.slug, lead_secret=agent.lead_secret)
    agent.schema_cache = schema if isinstance(schema, dict) else {"raw": schema}
    agent.last_schema_synced_at = datetime.now(UTC)
    db.add(
        OutperoSyncLog(
            workspace_id=agent.workspace_id,
            outpero_agent_id=agent.id,
            operation="schema.refresh",
            status="ok",
            detail="Fetched lead-intake schema",
            meta={"slug": agent.slug},
        )
    )
    db.commit()
    db.refresh(agent)
    return agent.schema_cache


def initiate_outbound_call(
    db: Session,
    *,
    agent: OutperoAgent,
    phone: str,
    name: str | None = None,
    pre_call: dict[str, Any] | None = None,
    is_test: bool = False,
    client: OutperoClient | None = None,
) -> dict[str, Any]:
    if agent.status != "active":
        raise ValueError("Agent is inactive")

    e164 = normalize_e164(phone)
    lead = db.execute(
        select(Lead).where(Lead.workspace_id == agent.workspace_id, Lead.phone_e164 == e164)
    ).scalar_one_or_none()
    if not lead:
        lead = Lead(
            workspace_id=agent.workspace_id,
            name=name,
            phone_e164=e164,
            status=LeadStatus.eligible,
            consent_source="outpero_test" if is_test else "outpero",
            lead_source="outpero",
            profile={"outpero_agent_id": str(agent.id), "outpero_agent_name": agent.name},
        )
        db.add(lead)
        db.flush()
    elif name and not lead.name:
        lead.name = name

    payload_pre_call: dict[str, Any] = dict(pre_call or {})
    if name:
        payload_pre_call.setdefault("lead_name", name)
    if is_test:
        payload_pre_call.setdefault("karyuk_test", True)

    # Context injection via pre-call variables (officially supported)
    prior_calls = db.scalars(
        select(Call)
        .where(
            Call.workspace_id == agent.workspace_id,
            Call.lead_id == lead.id,
            Call.provider == "outpero",
        )
        .order_by(Call.created_at.desc())
        .limit(3)
    ).all()
    if prior_calls:
        snippets = []
        for prior in prior_calls:
            bit = (prior.summary or prior.disposition or prior.outcome or "")[:180]
            if bit:
                snippets.append(str(bit))
        if snippets:
            payload_pre_call.setdefault(
                "previous_context",
                " | ".join(snippets)[:900],
            )

    client = client or OutperoClient()
    try:
        response = client.submit_lead(
            slug=agent.slug,
            lead_secret=agent.lead_secret,
            phone=e164,
            pre_call=payload_pre_call,
        )
    except OutperoApiError:
        db.add(
            OutperoSyncLog(
                workspace_id=agent.workspace_id,
                outpero_agent_id=agent.id,
                operation="lead.submit",
                status="error",
                detail="Failed to submit lead to Outpero",
                meta={"phone": e164[-4:].rjust(len(e164), "*"), "is_test": is_test},
            )
        )
        db.commit()
        raise

    external_call_id = None
    for key in ("call_id", "id", "callId"):
        if response.get(key):
            external_call_id = str(response[key])
            break
    # Some responses nest under data
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    if not external_call_id:
        for key in ("call_id", "id"):
            if data.get(key):
                external_call_id = str(data[key])
                break

    call = Call(
        workspace_id=agent.workspace_id,
        lead_id=lead.id,
        outpero_agent_id=agent.id,
        direction=CallDirection.outbound,
        outcome=CallOutcome.queued,
        duration_seconds=0,
        transcript=None,
        summary=None,
        captured_fields={
            "pre_call": payload_pre_call,
            "outpero_submit_response": {
                k: v for k, v in response.items() if k not in {"transcript", "recording_url"}
            },
            "is_test": is_test,
        },
        provider="outpero",
        provider_call_sid=external_call_id,
        is_test=is_test,
        started_at=datetime.now(UTC),
    )
    db.add(call)
    agent.last_activity_at = datetime.now(UTC)
    db.add(
        OutperoSyncLog(
            workspace_id=agent.workspace_id,
            outpero_agent_id=agent.id,
            operation="lead.submit",
            status="ok",
            detail="Submitted lead to Outpero lead-intake",
            meta={
                "lead_id": str(lead.id),
                "external_call_id": external_call_id,
                "is_test": is_test,
            },
        )
    )
    db.commit()
    db.refresh(call)
    db.refresh(lead)
    return {
        "call_id": call.id,
        "lead_id": lead.id,
        "provider_call_sid": call.provider_call_sid,
        "outcome": call.outcome.value if hasattr(call.outcome, "value") else call.outcome,
        "outpero_response": response,
        "is_test": is_test,
    }


def refresh_call_status(
    db: Session,
    *,
    agent: OutperoAgent,
    call: Call,
    client: OutperoClient | None = None,
) -> Call:
    if not call.provider_call_sid:
        raise ValueError("Call has no Outpero call id yet")
    client = client or OutperoClient()
    payload = client.get_call(
        slug=agent.slug,
        lead_secret=agent.lead_secret,
        call_id=call.provider_call_sid,
    )
    # Normalize into call.ended-like shape when possible
    if "call_id" not in payload:
        payload = {**payload, "call_id": call.provider_call_sid}
    if "event" not in payload:
        payload = {**payload, "event": "call.status"}
    process_call_ended_payload(
        db,
        workspace_id=agent.workspace_id,
        payload=payload,
        agent=agent,
        is_test=bool(call.is_test),
    )
    refreshed = db.get(Call, call.id)
    assert refreshed is not None
    return refreshed


def lead_context_for_phone(
    db: Session,
    *,
    workspace_id: UUID,
    phone: str,
) -> dict[str, Any]:
    e164 = normalize_e164(phone)
    lead = db.execute(
        select(Lead).where(Lead.workspace_id == workspace_id, Lead.phone_e164 == e164)
    ).scalar_one_or_none()
    if not lead:
        return {"found": False, "phone": e164, "context": ""}

    calls = db.scalars(
        select(Call)
        .where(Call.workspace_id == workspace_id, Call.lead_id == lead.id)
        .order_by(Call.created_at.desc())
        .limit(5)
    ).all()
    history = []
    for c in calls:
        history.append(
            {
                "call_id": str(c.id),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "outcome": c.outcome.value if hasattr(c.outcome, "value") else c.outcome,
                "disposition": c.disposition,
                "summary": c.summary,
            }
        )
    context_bits = [
        f"Name: {lead.name}" if lead.name else None,
        f"Qualification: {lead.qualification}" if lead.qualification else None,
        f"Interest: {lead.interest_level}" if lead.interest_level else None,
        f"Requirements: {lead.requirements}" if lead.requirements else None,
        f"Budget: {lead.budget}" if lead.budget else None,
    ]
    for item in history[:3]:
        if item.get("summary"):
            context_bits.append(f"Prior summary: {item['summary']}")
    context = "; ".join(b for b in context_bits if b)
    return {
        "found": True,
        "phone": e164,
        "lead": {
            "id": lead.id,
            "name": lead.name,
            "qualification": lead.qualification,
            "interest_level": lead.interest_level,
            "requirements": lead.requirements,
            "budget": lead.budget,
            "follow_up_required": lead.follow_up_required,
        },
        "recent_calls": history,
        "context": context[:1500],
    }
