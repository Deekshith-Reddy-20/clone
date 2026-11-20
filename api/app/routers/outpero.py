"""Outpero voice-agent API surface for the Karyuk dashboard."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_workspace_membership
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import Call, Lead, Membership
from app.models.outpero import OutperoAgent, OutperoSyncLog, OutperoWebhookEvent
from app.services.outpero.agents import (
    agent_stats,
    create_agent,
    get_agent,
    initiate_outbound_call,
    lead_context_for_phone,
    refresh_call_status,
    refresh_schema,
    serialize_agent,
    update_agent,
)
from app.services.outpero.client import OutperoApiError
from app.services.outpero.signatures import verify_outpero_signature
from app.services.outpero.sync import build_event_key, process_call_ended_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["outpero"])
workspace_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/outpero",
    tags=["outpero"],
)
webhook_router = APIRouter(prefix="/v1/webhooks/outpero", tags=["outpero-webhooks"])


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=128)
    lead_secret: str = Field(min_length=1, max_length=255)
    webhook_signing_secret: str | None = Field(default=None, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    lead_secret: str | None = Field(default=None, min_length=1, max_length=255)
    webhook_signing_secret: str | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    config: dict[str, Any] | None = None


class TestCallRequest(BaseModel):
    phone: str
    name: str | None = None
    pre_call: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


class LeadContextRequest(BaseModel):
    phone: str


def _serialize_lead(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "name": lead.name,
        "phone_e164": lead.phone_e164,
        "status": lead.status.value if hasattr(lead.status, "value") else lead.status,
        "email": lead.email,
        "company": lead.company,
        "location": lead.location,
        "lead_source": lead.lead_source,
        "qualification": lead.qualification,
        "interest_level": lead.interest_level,
        "requirements": lead.requirements,
        "budget": lead.budget,
        "follow_up_required": lead.follow_up_required,
        "next_follow_up_at": lead.next_follow_up_at,
        "last_interaction_at": lead.last_interaction_at,
        "profile": lead.profile or {},
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
    }


def _serialize_call(call: Call, *, agent: OutperoAgent | None = None, lead: Lead | None = None) -> dict[str, Any]:
    outcome = call.outcome.value if hasattr(call.outcome, "value") else call.outcome
    direction = call.direction.value if hasattr(call.direction, "value") else call.direction
    return {
        "id": call.id,
        "lead_id": call.lead_id,
        "outpero_agent_id": call.outpero_agent_id,
        "agent_name": agent.name if agent else None,
        "lead_name": lead.name if lead else None,
        "lead_phone": lead.phone_e164 if lead else None,
        "direction": direction,
        "outcome": outcome,
        "disposition": call.disposition,
        "duration_seconds": call.duration_seconds,
        "transcript": call.transcript,
        "summary": call.summary,
        "captured_fields": call.captured_fields or {},
        "recording_url": call.recording_url,
        "provider": call.provider,
        "provider_call_sid": call.provider_call_sid,
        "is_test": call.is_test,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "created_at": call.created_at,
        "finalized_at": call.finalized_at,
        "realtime": outcome
        not in ("completed", "failed", "canceled", "busy", "no_answer"),
    }


@workspace_router.get("/status")
def outpero_status(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    count = len(
        db.scalars(select(OutperoAgent).where(OutperoAgent.workspace_id == workspace_id)).all()
    )
    return {
        "configured": count > 0,
        "agent_count": count,
        "api_base_url": settings.outpero_api_base_url,
        "webhook_url": f"{settings.public_api_base_url.rstrip('/')}/v1/webhooks/outpero/{workspace_id}",
        "action_context_url": (
            f"{settings.public_api_base_url.rstrip('/')}/v1/webhooks/outpero/{workspace_id}/lead-context"
        ),
        "supported_operations": [
            "register_agent_locally",
            "refresh_schema",
            "submit_lead_intake_call",
            "poll_call_status",
            "receive_call_ended_webhook",
            "sync_leads_and_transcripts",
            "mid_call_lead_context_action",
        ],
        "unsupported_operations": [
            "list_agents_from_outpero_api",
            "update_agent_prompt_via_api",
            "activate_deactivate_in_outpero",
            "browser_based_voice_test",
            "list_full_call_history_from_outpero_api",
            "webhook_retries_from_outpero",
        ],
    }


@workspace_router.get("/agents")
def list_agents(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    agents = db.scalars(
        select(OutperoAgent)
        .where(OutperoAgent.workspace_id == workspace_id)
        .order_by(OutperoAgent.created_at.desc())
    ).all()
    return [serialize_agent(a, stats=agent_stats(db, a)) for a in agents]


@workspace_router.post("/agents", status_code=201)
def register_agent(
    workspace_id: UUID,
    body: AgentCreate,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        agent = create_agent(
            db,
            workspace_id=workspace_id,
            name=body.name,
            slug=body.slug,
            lead_secret=body.lead_secret,
            webhook_signing_secret=body.webhook_signing_secret,
            config=body.config,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent slug already registered") from exc
    return serialize_agent(agent, stats=agent_stats(db, agent))


@workspace_router.get("/agents/{agent_id}")
def get_agent_detail(
    workspace_id: UUID,
    agent_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    agent = get_agent(db, workspace_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return serialize_agent(agent, stats=agent_stats(db, agent))


@workspace_router.patch("/agents/{agent_id}")
def patch_agent(
    workspace_id: UUID,
    agent_id: UUID,
    body: AgentUpdate,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    agent = get_agent(db, workspace_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        agent = update_agent(
            db,
            agent,
            name=body.name,
            lead_secret=body.lead_secret,
            webhook_signing_secret=body.webhook_signing_secret,
            status=body.status,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_agent(agent, stats=agent_stats(db, agent))


@workspace_router.post("/agents/{agent_id}/refresh-schema")
def agent_refresh_schema(
    workspace_id: UUID,
    agent_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    agent = get_agent(db, workspace_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        schema = refresh_schema(db, agent)
    except OutperoApiError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
    return {"agent_id": agent.id, "schema": schema, "synced_at": agent.last_schema_synced_at}


@workspace_router.post("/agents/{agent_id}/test-calls", status_code=202)
def agent_test_call(
    workspace_id: UUID,
    agent_id: UUID,
    body: TestCallRequest,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to place a real Outpero test call to the given phone number",
        )
    agent = get_agent(db, workspace_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        result = initiate_outbound_call(
            db,
            agent=agent,
            phone=body.phone,
            name=body.name,
            pre_call=body.pre_call,
            is_test=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OutperoApiError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
    return result


@workspace_router.post("/agents/{agent_id}/calls", status_code=202)
def agent_place_call(
    workspace_id: UUID,
    agent_id: UUID,
    body: TestCallRequest,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to place a real Outpero call")
    agent = get_agent(db, workspace_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        result = initiate_outbound_call(
            db,
            agent=agent,
            phone=body.phone,
            name=body.name,
            pre_call=body.pre_call,
            is_test=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OutperoApiError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
    return result


@workspace_router.post("/calls/{call_id}/refresh")
def refresh_outpero_call(
    workspace_id: UUID,
    call_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    call = db.get(Call, call_id)
    if not call or call.workspace_id != workspace_id or call.provider != "outpero":
        raise HTTPException(status_code=404, detail="Outpero call not found")
    if not call.outpero_agent_id:
        raise HTTPException(status_code=400, detail="Call is not linked to an Outpero agent")
    agent = get_agent(db, workspace_id, call.outpero_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        call = refresh_call_status(db, agent=agent, call=call)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OutperoApiError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
    lead = db.get(Lead, call.lead_id) if call.lead_id else None
    return _serialize_call(call, agent=agent, lead=lead)


@workspace_router.get("/calls")
def list_outpero_calls(
    workspace_id: UUID,
    agent_id: UUID | None = None,
    outcome: str | None = None,
    disposition: str | None = None,
    is_test: bool | None = None,
    generated_lead: bool | None = None,
    follow_up: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Call).where(Call.workspace_id == workspace_id, Call.provider == "outpero")
    if agent_id:
        stmt = stmt.where(Call.outpero_agent_id == agent_id)
    if outcome:
        stmt = stmt.where(Call.outcome == outcome)
    if disposition:
        stmt = stmt.where(Call.disposition == disposition)
    if is_test is not None:
        stmt = stmt.where(Call.is_test.is_(is_test))
    if generated_lead is True:
        stmt = stmt.where(Call.lead_id.is_not(None))
    stmt = stmt.order_by(Call.created_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()

    agent_ids = {c.outpero_agent_id for c in rows if c.outpero_agent_id}
    lead_ids = {c.lead_id for c in rows if c.lead_id}
    agents = {
        a.id: a
        for a in db.scalars(select(OutperoAgent).where(OutperoAgent.id.in_(agent_ids))).all()
    } if agent_ids else {}
    leads = {
        l.id: l for l in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()
    } if lead_ids else {}

    results = []
    for call in rows:
        lead = leads.get(call.lead_id) if call.lead_id else None
        if follow_up is True and not (lead and lead.follow_up_required):
            continue
        results.append(
            _serialize_call(
                call,
                agent=agents.get(call.outpero_agent_id) if call.outpero_agent_id else None,
                lead=lead,
            )
        )
    return results


@workspace_router.get("/leads")
def list_outpero_leads(
    workspace_id: UUID,
    agent_id: UUID | None = None,
    qualification: str | None = None,
    status: str | None = None,
    q: str | None = None,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Lead).where(
        Lead.workspace_id == workspace_id,
        Lead.lead_source == "outpero",
    )
    if qualification:
        stmt = stmt.where(Lead.qualification == qualification)
    if status:
        stmt = stmt.where(Lead.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (Lead.name.ilike(like))
            | (Lead.phone_e164.ilike(like))
            | (Lead.email.ilike(like))
            | (Lead.company.ilike(like))
        )
    leads = db.scalars(stmt.order_by(Lead.last_interaction_at.desc().nullslast())).all()

    if agent_id:
        filtered = []
        for lead in leads:
            profile = lead.profile or {}
            if profile.get("outpero_agent_id") == str(agent_id):
                filtered.append(lead)
                continue
            linked = db.scalar(
                select(Call.id).where(
                    Call.lead_id == lead.id,
                    Call.outpero_agent_id == agent_id,
                    Call.provider == "outpero",
                ).limit(1)
            )
            if linked:
                filtered.append(lead)
        leads = filtered

    payload = []
    for lead in leads:
        item = _serialize_lead(lead)
        last_call = db.scalar(
            select(Call)
            .where(Call.lead_id == lead.id, Call.provider == "outpero")
            .order_by(Call.created_at.desc())
            .limit(1)
        )
        item["last_call"] = (
            {
                "id": last_call.id,
                "created_at": last_call.created_at,
                "disposition": last_call.disposition,
                "outcome": last_call.outcome.value
                if last_call and hasattr(last_call.outcome, "value")
                else (last_call.outcome if last_call else None),
                "outpero_agent_id": last_call.outpero_agent_id if last_call else None,
            }
            if last_call
            else None
        )
        payload.append(item)
    return payload


@workspace_router.get("/leads/{lead_id}/history")
def lead_conversation_history(
    workspace_id: UUID,
    lead_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    lead = db.get(Lead, lead_id)
    if not lead or lead.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Lead not found")
    calls = db.scalars(
        select(Call)
        .where(Call.workspace_id == workspace_id, Call.lead_id == lead_id)
        .order_by(Call.created_at.asc())
    ).all()
    agents = {
        a.id: a
        for a in db.scalars(
            select(OutperoAgent).where(
                OutperoAgent.id.in_({c.outpero_agent_id for c in calls if c.outpero_agent_id})
            )
        ).all()
    } if any(c.outpero_agent_id for c in calls) else {}
    return {
        "lead": _serialize_lead(lead),
        "interactions": [_serialize_call(c, agent=agents.get(c.outpero_agent_id) if c.outpero_agent_id else None, lead=lead) for c in calls],
    }


@workspace_router.get("/sync-logs")
def list_sync_logs(
    workspace_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(OutperoSyncLog)
        .where(OutperoSyncLog.workspace_id == workspace_id)
        .order_by(OutperoSyncLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "operation": r.operation,
            "status": r.status,
            "detail": r.detail,
            "meta": r.meta,
            "outpero_agent_id": r.outpero_agent_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def _process_webhook_background(
    *,
    workspace_id: UUID,
    agent_id: UUID | None,
    event_id: UUID,
    payload: dict[str, Any],
    is_test: bool,
) -> None:
    db = SessionLocal()
    try:
        event = db.get(OutperoWebhookEvent, event_id)
        agent = db.get(OutperoAgent, agent_id) if agent_id else None
        if agent and agent.workspace_id != workspace_id:
            agent = None
        try:
            process_call_ended_payload(
                db,
                workspace_id=workspace_id,
                payload=payload,
                agent=agent,
                event_row=event,
                is_test=is_test,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("outpero_webhook_process_failed event=%s", event_id)
            if event:
                event.status = "failed"
                event.error_message = str(exc)[:1000]
                db.commit()
    finally:
        db.close()


@webhook_router.post("/{workspace_id}")
async def outpero_call_ended_webhook(
    workspace_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_outpero_timestamp: str | None = Header(default=None, alias="X-Outpero-Timestamp"),
    x_outpero_signature: str | None = Header(default=None, alias="X-Outpero-Signature"),
    x_outpero_agent_slug: str | None = Header(default=None, alias="X-Outpero-Agent-Slug"),
) -> dict[str, Any]:
    raw = await request.body()
    settings = get_settings()

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    agent: OutperoAgent | None = None
    slug = x_outpero_agent_slug or str(payload.get("employee") or payload.get("slug") or "")
    if slug:
        agent = db.execute(
            select(OutperoAgent).where(
                OutperoAgent.workspace_id == workspace_id,
                OutperoAgent.slug == slug,
            )
        ).scalar_one_or_none()

    # If only one agent is configured, use it for signature verification
    if agent is None:
        agents = db.scalars(
            select(OutperoAgent).where(OutperoAgent.workspace_id == workspace_id)
        ).all()
        if len(agents) == 1:
            agent = agents[0]

    secret = (
        (agent.webhook_signing_secret if agent and agent.webhook_signing_secret else None)
        or settings.outpero_webhook_shared_secret
        or ""
    )
    signature_required = bool(secret)
    if signature_required:
        ok = verify_outpero_signature(
            secret=secret,
            timestamp=x_outpero_timestamp,
            signature_header=x_outpero_signature,
            raw_body=raw,
            max_age_seconds=settings.outpero_webhook_max_age_seconds,
        )
        if not ok:
            logger.warning("outpero_webhook_invalid_signature workspace=%s", workspace_id)
            raise HTTPException(status_code=401, detail="Invalid Outpero webhook signature")

    event_key = build_event_key(payload)
    existing = db.execute(
        select(OutperoWebhookEvent).where(
            OutperoWebhookEvent.workspace_id == workspace_id,
            OutperoWebhookEvent.event_key == event_key,
        )
    ).scalar_one_or_none()
    if existing and existing.status == "processed":
        return {"accepted": True, "duplicate": True, "event_id": existing.id}

    if existing is None:
        existing = OutperoWebhookEvent(
            workspace_id=workspace_id,
            outpero_agent_id=agent.id if agent else None,
            event_key=event_key,
            external_call_id=str(payload.get("call_id") or "") or None,
            event_type=str(payload.get("event") or "call.ended"),
            payload=payload,
            status="received",
        )
        db.add(existing)
        try:
            db.commit()
            db.refresh(existing)
        except IntegrityError:
            db.rollback()
            existing = db.execute(
                select(OutperoWebhookEvent).where(
                    OutperoWebhookEvent.workspace_id == workspace_id,
                    OutperoWebhookEvent.event_key == event_key,
                )
            ).scalar_one()
            return {"accepted": True, "duplicate": True, "event_id": existing.id}

    pre_call = payload.get("pre_call") if isinstance(payload.get("pre_call"), dict) else {}
    is_test = bool(payload.get("karyuk_test") or pre_call.get("karyuk_test"))
    background_tasks.add_task(
        _process_webhook_background,
        workspace_id=workspace_id,
        agent_id=agent.id if agent else None,
        event_id=existing.id,
        payload=payload,
        is_test=is_test,
    )
    return {"accepted": True, "duplicate": False, "event_id": existing.id}


@webhook_router.post("/{workspace_id}/lead-context")
def outpero_mid_call_lead_context(
    workspace_id: UUID,
    body: LeadContextRequest,
    db: Session = Depends(get_db),
    x_outpero_action_secret: str | None = Header(default=None, alias="X-Outpero-Action-Secret"),
    x_outpero_agent_slug: str | None = Header(default=None, alias="X-Outpero-Agent-Slug"),
) -> dict[str, Any]:
    """Custom API Action target: return prior lead context during a live Outpero call."""
    agent: OutperoAgent | None = None
    if x_outpero_agent_slug:
        agent = db.execute(
            select(OutperoAgent).where(
                OutperoAgent.workspace_id == workspace_id,
                OutperoAgent.slug == x_outpero_agent_slug,
            )
        ).scalar_one_or_none()
    if agent is None:
        agents = db.scalars(
            select(OutperoAgent).where(OutperoAgent.workspace_id == workspace_id)
        ).all()
        if len(agents) == 1:
            agent = agents[0]
    if not agent or not agent.action_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not x_outpero_action_secret or x_outpero_action_secret != agent.action_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        return lead_context_for_phone(db, workspace_id=workspace_id, phone=body.phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Aggregate for include_router
router.include_router(workspace_router)
router.include_router(webhook_router)
