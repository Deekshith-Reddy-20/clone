import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_workspace_membership
from app.database import get_db
from app.models import (
    AuditEvent,
    Call,
    CallRequest,
    VoiceBookingRequest,
    Campaign,
    CampaignRecipient,
    Employee,
    IngressIntegration,
    IntegrationConnection,
    KnowledgeSource,
    Lead,
    Membership,
    Notification,
    PhoneNumber,
    SuppressionRecord,
    User,
    WalletLedgerEntry,
    WebhookDelivery,
    WebhookEndpoint,
    WorkspaceSettings,
)
from app.models.enums import (
    CampaignStatus,
    EmployeeStatus,
    KnowledgeStatus,
    LeadStatus,
    PhoneNumberStatus,
)
from app.services.audit import log_audit
from app.services.calls import simulate_inbound_call, simulate_outbound_call, sync_exotel_call
from app.services.phone import national_exophone_display, normalize_e164
from app.services.telephony import telephony_status_payload
from app.services.wallet import get_wallet, top_up

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["platform"])


@router.get("/telephony/status")
def workspace_telephony_status(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
) -> dict:
    _ = workspace_id
    return telephony_status_payload()


@router.post("/calls/{call_id}/sync-provider")
def sync_provider_call(
    workspace_id: UUID,
    call_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> dict:
    call = db.get(Call, call_id)
    if not call or call.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Call not found")
    sync_exotel_call(db, call)
    outcome = call.outcome.value if hasattr(call.outcome, "value") else call.outcome
    return {
        "id": call.id,
        "outcome": outcome,
        "provider": call.provider,
        "realtime": outcome not in ("completed", "failed", "canceled", "busy", "no_answer"),
    }


# --- M03 Knowledge ---
class KnowledgeCreate(BaseModel):
    title: str
    content: str = Field(min_length=1)


@router.get("/knowledge/sources")
def list_knowledge(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(KnowledgeSource)
        .where(KnowledgeSource.workspace_id == workspace_id)
        .order_by(KnowledgeSource.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "content": r.content,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/knowledge/sources", status_code=201)
def create_knowledge(
    workspace_id: UUID,
    body: KnowledgeCreate,
    membership: Membership = Depends(get_workspace_membership),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = KnowledgeSource(
        workspace_id=workspace_id,
        title=body.title,
        content=body.content,
        status=KnowledgeStatus.ready,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(db, workspace_id=workspace_id, actor_user_id=user.id, action="knowledge.created", summary=body.title)
    return {"id": row.id, "status": row.status}


@router.post("/knowledge/sources/upload", status_code=201)
async def upload_knowledge_pdf(
    workspace_id: UUID,
    file: UploadFile = File(...),
    membership: Membership = Depends(get_workspace_membership),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add workspace knowledge from a PDF when there is no website (or as extra docs)."""
    from app.services.pdf_knowledge import extract_pdf_text

    _ = membership
    data = await file.read()
    name = (file.filename or "document.pdf").strip() or "document.pdf"
    try:
        content = extract_pdf_text(data, filename=name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    title = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if title.lower().endswith(".pdf"):
        title = title[:-4]
    row = KnowledgeSource(
        workspace_id=workspace_id,
        title=title or "PDF upload",
        content=content,
        status=KnowledgeStatus.ready,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(db, workspace_id=workspace_id, actor_user_id=user.id, action="knowledge.uploaded", summary=row.title)
    return {"id": row.id, "status": row.status, "title": row.title, "content_chars": len(content)}


# --- M04 Leads ---
class LeadCreate(BaseModel):
    name: str | None = None
    phone: str
    consent_source: str | None = "manual"


class CsvImport(BaseModel):
    csv_text: str


@router.get("/booking-requests")
def list_voice_booking_requests(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(VoiceBookingRequest)
        .where(VoiceBookingRequest.workspace_id == workspace_id)
        .order_by(VoiceBookingRequest.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": r.id,
            "status": r.status,
            "call_id": r.call_id,
            "caller_phone": r.caller_phone,
            "details": r.details,
            "note": r.note,
            "notify_status": r.notify_status,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/leads")
def list_leads(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Lead).where(Lead.workspace_id == workspace_id)).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "phone_e164": r.phone_e164,
            "status": r.status.value if hasattr(r.status, "value") else r.status,
            "email": r.email,
            "company": r.company,
            "location": r.location,
            "lead_source": r.lead_source,
            "qualification": r.qualification,
            "interest_level": r.interest_level,
            "requirements": r.requirements,
            "budget": r.budget,
            "follow_up_required": r.follow_up_required,
            "next_follow_up_at": r.next_follow_up_at,
            "last_interaction_at": r.last_interaction_at,
            "consent_source": r.consent_source,
            "created_at": r.created_at,
            "owner_notify_status": (r.profile or {}).get("owner_notify_status"),
            "owner_notify_channel": (r.profile or {}).get("owner_notify_channel"),
        }
        for r in rows
    ]


@router.post("/leads", status_code=201)
def create_lead(
    workspace_id: UUID,
    body: LeadCreate,
    membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    try:
        e164 = normalize_e164(body.phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid phone") from exc
    suppressed = db.execute(
        select(SuppressionRecord).where(
            SuppressionRecord.workspace_id == workspace_id,
            SuppressionRecord.phone_e164 == e164,
        )
    ).scalar_one_or_none()
    lead = Lead(
        workspace_id=workspace_id,
        name=body.name,
        phone_e164=e164,
        status=LeadStatus.suppressed if suppressed else LeadStatus.eligible,
        consent_source=body.consent_source,
    )
    db.add(lead)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Lead with this phone already exists") from exc
    db.refresh(lead)
    status = lead.status.value if hasattr(lead.status, "value") else lead.status
    return {"id": lead.id, "phone_e164": lead.phone_e164, "status": status}


@router.post("/lead-imports", status_code=202)
def import_leads_csv(
    workspace_id: UUID,
    body: CsvImport,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    created, invalid = 0, 0
    for line in body.csv_text.strip().splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            invalid += 1
            continue
        name, phone = parts[0], parts[1]
        try:
            e164 = normalize_e164(phone)
        except ValueError:
            invalid += 1
            continue
        exists = db.execute(
            select(Lead).where(Lead.workspace_id == workspace_id, Lead.phone_e164 == e164)
        ).scalar_one_or_none()
        if exists:
            continue
        db.add(
            Lead(
                workspace_id=workspace_id,
                name=name,
                phone_e164=e164,
                status=LeadStatus.eligible,
                consent_source="csv",
            )
        )
        created += 1
    db.commit()
    return {"created": created, "invalid_rows": invalid}


@router.post("/suppression-records", status_code=201)
def add_suppression(
    workspace_id: UUID,
    body: LeadCreate,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    e164 = normalize_e164(body.phone)
    db.add(
        SuppressionRecord(workspace_id=workspace_id, phone_e164=e164, reason="manual_opt_out")
    )
    lead = db.execute(
        select(Lead).where(Lead.workspace_id == workspace_id, Lead.phone_e164 == e164)
    ).scalar_one_or_none()
    if lead:
        lead.status = LeadStatus.suppressed
    db.commit()
    return {"phone_e164": e164, "status": "suppressed"}


# --- M05 Numbers ---
def _supersede_other_exophone_registrations(
    db: Session,
    e164: str,
    workspace_id: UUID,
    keep_id: UUID,
) -> None:
  """Only one workspace should answer a given ExoPhone; disable stale rows elsewhere."""
  from app.services.phone import e164_variants

  variants = e164_variants(e164)
  others = db.scalars(
    select(PhoneNumber).where(
        PhoneNumber.id != keep_id,
        PhoneNumber.inbound_enabled.is_(True),
    )
  ).all()
  for row in others:
    if e164_variants(row.e164) & variants:
      row.inbound_enabled = False


class PhoneRegister(BaseModel):
    e164: str
    employee_id: UUID | None = None


@router.get("/phone-numbers")
def list_numbers(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(PhoneNumber).where(PhoneNumber.workspace_id == workspace_id)).all()
    return [
        {
            "id": r.id,
            "e164": r.e164,
            "dial_national": national_exophone_display(r.e164),
            "status": r.status,
            "employee_id": r.employee_id,
            "inbound_enabled": r.inbound_enabled,
        }
        for r in rows
    ]


@router.post("/phone-numbers", status_code=201)
def register_number(
    workspace_id: UUID,
    body: PhoneRegister,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    try:
        e164 = normalize_e164(body.e164)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.employee_id:
        emp = db.get(Employee, body.employee_id)
        if not emp or emp.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Employee not in this workspace")
        if emp.status != EmployeeStatus.published:
            raise HTTPException(
                status_code=400,
                detail="Publish the employee on Team before routing inbound calls",
            )

    existing = db.execute(
        select(PhoneNumber).where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.e164 == e164,
        )
    ).scalar_one_or_none()
    if existing:
        existing.employee_id = body.employee_id
        existing.inbound_enabled = True
        existing.status = PhoneNumberStatus.active
        _supersede_other_exophone_registrations(db, e164, workspace_id, existing.id)
        db.commit()
        db.refresh(existing)
        log_audit(
            db,
            workspace_id=workspace_id,
            actor_user_id=user.id,
            action="number.updated",
            summary=e164,
        )
        return {"id": existing.id, "status": existing.status, "updated": True}

    row = PhoneNumber(
        workspace_id=workspace_id,
        e164=e164,
        status=PhoneNumberStatus.active,
        employee_id=body.employee_id,
        inbound_enabled=True,
    )
    db.add(row)
    db.flush()
    _supersede_other_exophone_registrations(db, e164, workspace_id, row.id)
    db.commit()
    db.refresh(row)
    log_audit(db, workspace_id=workspace_id, actor_user_id=user.id, action="number.registered", summary=e164)
    return {"id": row.id, "status": row.status, "updated": False}


@router.put("/phone-numbers/{number_id}/route")
def route_number(
    workspace_id: UUID,
    number_id: UUID,
    body: PhoneRegister,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    row = db.get(PhoneNumber, number_id)
    if not row or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Not found")
    if body.employee_id:
        emp = db.get(Employee, body.employee_id)
        if not emp or emp.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Employee not in this workspace")
        if emp.status != EmployeeStatus.published:
            raise HTTPException(status_code=400, detail="Employee must be published")
    row.employee_id = body.employee_id
    row.inbound_enabled = True
    db.commit()
    return {"id": row.id, "employee_id": row.employee_id}


# --- M07 Instant ---
class InstantCall(BaseModel):
    lead_id: UUID
    employee_id: UUID


@router.post("/call-requests", status_code=202)
def instant_call(
    workspace_id: UUID,
    body: InstantCall,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    key = idempotency_key or f"instant-{body.lead_id}-{body.employee_id}"
    existing = db.execute(
        select(CallRequest).where(
            CallRequest.workspace_id == workspace_id,
            CallRequest.idempotency_key == key,
        )
    ).scalar_one_or_none()
    if existing:
        return {"request_id": existing.id, "call_id": existing.call_id, "status": existing.status}
    req = CallRequest(
        workspace_id=workspace_id,
        idempotency_key=key,
        lead_id=body.lead_id,
        employee_id=body.employee_id,
        status="accepted",
    )
    db.add(req)
    db.flush()
    try:
        call = simulate_outbound_call(
            db, workspace_id=workspace_id, employee_id=body.employee_id, lead_id=body.lead_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    req.call_id = call.id
    req.status = "completed"
    db.commit()
    return {"request_id": req.id, "call_id": call.id, "status": req.status}


@router.post("/employees/{employee_id}/test-calls", status_code=202)
def test_call(
    workspace_id: UUID,
    employee_id: UUID,
    body: LeadCreate,
    membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    e164 = normalize_e164(body.phone)
    lead = db.execute(
        select(Lead).where(Lead.workspace_id == workspace_id, Lead.phone_e164 == e164)
    ).scalar_one_or_none()
    if not lead:
        lead = Lead(
            workspace_id=workspace_id,
            name=body.name or "Test lead",
            phone_e164=e164,
            status=LeadStatus.eligible,
            consent_source="test",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
    try:
        call = simulate_outbound_call(
            db, workspace_id=workspace_id, employee_id=employee_id, lead_id=lead.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    outcome = call.outcome.value if hasattr(call.outcome, "value") else call.outcome
    return {
        "call_id": call.id,
        "outcome": outcome,
        "provider": call.provider,
        "livekit_room": call.livekit_room,
        "realtime": outcome not in ("completed", "failed", "canceled", "busy", "no_answer"),
    }


# --- M08 Campaigns ---
class CampaignCreate(BaseModel):
    name: str
    employee_id: UUID
    lead_ids: list[UUID] = Field(default_factory=list)


@router.get("/campaigns")
def list_campaigns(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Campaign).where(Campaign.workspace_id == workspace_id)).all()
    return [{"id": c.id, "name": c.name, "status": c.status} for c in rows]


@router.post("/campaigns", status_code=201)
def create_campaign(
    workspace_id: UUID,
    body: CampaignCreate,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    campaign = Campaign(
        workspace_id=workspace_id,
        name=body.name,
        employee_id=body.employee_id,
        status=CampaignStatus.draft,
        config={},
    )
    db.add(campaign)
    db.flush()
    for lid in body.lead_ids:
        db.add(
            CampaignRecipient(
                campaign_id=campaign.id,
                workspace_id=workspace_id,
                lead_id=lid,
                status="pending",
            )
        )
    db.commit()
    db.refresh(campaign)
    return {"id": campaign.id, "status": campaign.status}


@router.post("/campaigns/{campaign_id}/commands")
def campaign_command(
    workspace_id: UUID,
    campaign_id: UUID,
    command: str = Query(...),
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if command == "start":
        campaign.status = CampaignStatus.running
        recipients = db.scalars(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status == "pending",
            )
        ).all()
        for rec in recipients:
            try:
                call = simulate_outbound_call(
                    db,
                    workspace_id=workspace_id,
                    employee_id=campaign.employee_id,
                    lead_id=rec.lead_id,
                    campaign_id=campaign.id,
                )
                rec.call_id = call.id
                rec.status = "completed"
            except ValueError:
                rec.status = "failed"
        campaign.status = CampaignStatus.completed
    elif command == "pause":
        campaign.status = CampaignStatus.paused
    elif command == "cancel":
        campaign.status = CampaignStatus.canceled
    db.commit()
    return {"id": campaign.id, "status": campaign.status}


# --- M09 Inbound ---
class InboundSimulate(BaseModel):
    caller_phone: str
    employee_id: UUID


@router.post("/incoming-calls/simulate", status_code=202)
def simulate_incoming(
    workspace_id: UUID,
    body: InboundSimulate,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    caller = normalize_e164(body.caller_phone)
    try:
        call = simulate_inbound_call(
            db, workspace_id=workspace_id, employee_id=body.employee_id, caller_e164=caller
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"call_id": call.id}


# --- M10 Calls & analytics ---
@router.get("/calls")
def list_calls(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Call).where(Call.workspace_id == workspace_id).order_by(Call.created_at.desc())
    ).all()
    return [
        {
            "id": c.id,
            "direction": c.direction,
            "outcome": c.outcome,
            "duration_seconds": c.duration_seconds,
            "cost_paise": c.cost_paise,
            "created_at": c.created_at,
            "provider": c.provider,
            "lead_id": c.lead_id,
            "disposition": c.disposition,
            "is_test": c.is_test,
            "outpero_agent_id": c.outpero_agent_id,
            "summary": c.summary,
        }
        for c in rows
    ]


@router.get("/calls/{call_id}")
def get_call(
    workspace_id: UUID,
    call_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    call = db.get(Call, call_id)
    if not call or call.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Not found")
    outcome = call.outcome.value if hasattr(call.outcome, "value") else call.outcome
    fields = dict(call.captured_fields or {})
    trace = fields.get("voice_turn_trace")
    if not trace:
        from app.models.call_turn_event import CallTurnEvent
        from sqlalchemy import select

        rows = db.scalars(
            select(CallTurnEvent)
            .where(CallTurnEvent.call_id == call_id)
            .order_by(CallTurnEvent.turn_index)
            .limit(200)
        ).all()
        if rows:
            fields["voice_turn_trace"] = [r.payload for r in rows]
    return {
        "id": call.id,
        "lead_id": call.lead_id,
        "transcript": call.transcript,
        "summary": call.summary,
        "captured_fields": fields,
        "outcome": outcome,
        "disposition": call.disposition,
        "duration_seconds": call.duration_seconds,
        "cost_paise": call.cost_paise,
        "provider": call.provider,
        "provider_call_sid": call.provider_call_sid,
        "livekit_room": call.livekit_room,
        "recording_url": call.recording_url,
        "is_test": call.is_test,
        "outpero_agent_id": call.outpero_agent_id,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "created_at": call.created_at,
        "finalized_at": call.finalized_at,
        "realtime": outcome not in ("completed", "failed", "canceled", "busy", "no_answer"),
    }


@router.get("/analytics/overview")
def analytics_overview(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(Call).where(Call.workspace_id == workspace_id)) or 0
    connected = db.scalar(
        select(func.count()).select_from(Call).where(
            Call.workspace_id == workspace_id,
            Call.outcome == "completed",
        )
    ) or 0
    return {
        "attempted": total,
        "connected": connected,
        "completion_rate": (connected / total) if total else 0,
    }


# --- M11 Integrations ---
@router.get("/integrations")
def list_integrations(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(IntegrationConnection).where(IntegrationConnection.workspace_id == workspace_id)
    ).all()
    return [{"id": r.id, "integration_type": r.integration_type, "status": r.status} for r in rows]


@router.post("/integrations/{integration_type}/connect", status_code=201)
def connect_integration(
    workspace_id: UUID,
    integration_type: str,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    row = IntegrationConnection(
        workspace_id=workspace_id,
        integration_type=integration_type,
        status="connected",
        config={"sandbox": True},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


# --- M12 Webhooks ---
class WebhookCreate(BaseModel):
    url: str
    events: list[str] = Field(default_factory=lambda: ["call.finalized.v1"])


@router.get("/webhook-endpoints")
def list_webhooks(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.workspace_id == workspace_id)).all()
    return [{"id": r.id, "url": r.url, "events": r.events} for r in rows]


@router.post("/webhook-endpoints", status_code=201)
def create_webhook(
    workspace_id: UUID,
    body: WebhookCreate,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    secret = secrets.token_hex(16)
    row = WebhookEndpoint(
        workspace_id=workspace_id,
        url=body.url,
        signing_secret=secret,
        events=body.events,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "signing_secret": secret}


@router.get("/webhook-deliveries")
def list_deliveries(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(WebhookDelivery).where(WebhookDelivery.workspace_id == workspace_id).limit(50)
    ).all()
    return [
        {"id": d.id, "event_type": d.event_type, "status": d.status, "response_code": d.response_code}
        for d in rows
    ]


# --- M13 Wallet ---
@router.get("/wallet")
def wallet_view(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    account = get_wallet(db, workspace_id)
    credits = account.balance_paise // 100
    reserved = account.reserved_paise // 100
    return {
        "balance_paise": account.balance_paise,
        "reserved_paise": account.reserved_paise,
        "credits": credits,
        "reserved_credits": reserved,
        "available_credits": credits - reserved,
    }


class TopUp(BaseModel):
    credits: int = Field(ge=1)


@router.post("/wallet/top-ups", status_code=201)
def wallet_topup(
    workspace_id: UUID,
    body: TopUp,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    account = top_up(db, workspace_id, body.credits * 100)
    return {"balance_paise": account.balance_paise}


@router.get("/wallet/transactions")
def wallet_transactions(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(WalletLedgerEntry)
        .where(WalletLedgerEntry.workspace_id == workspace_id)
        .order_by(WalletLedgerEntry.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "entry_type": e.entry_type,
            "amount_paise": e.amount_paise,
            "reference": e.reference,
            "created_at": e.created_at,
        }
        for e in rows
    ]


# --- M14 Settings ---
class OwnerNotifyPatch(BaseModel):
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None


class OwnerNotifyTestBody(BaseModel):
    channel: str  # email | sms | whatsapp


class SettingsPatch(BaseModel):
    timezone: str | None = None
    retention_days: int | None = None
    owner_notify: OwnerNotifyPatch | None = None


@router.get("/workspace-settings")
def get_settings(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not row:
        row = WorkspaceSettings(workspace_id=workspace_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    notes = row.notifications if isinstance(row.notifications, dict) else {}
    owner = notes.get("owner") if isinstance(notes.get("owner"), dict) else {}
    from app.config import get_settings as app_settings
    from app.services.owner_notify import CHANNELS, channel_configured, owner_contact, verified_map

    s = app_settings()
    contacts = owner_contact(owner, s)
    return {
        "timezone": row.timezone,
        "retention_days": row.retention_days,
        "notifications": row.notifications,
        "owner_notify": {
            "contacts": contacts,
            "verified": verified_map(owner),
            "channels": {
                ch: {
                    "address": contacts.get(ch),
                    "credentials_ready": channel_configured(ch, contacts, s),
                    "verified": verified_map(owner).get(ch, False),
                    "last_test": (owner.get("last_test") or {}).get(ch),
                }
                for ch in CHANNELS
            },
        },
    }


@router.patch("/workspace-settings")
def patch_settings(
    workspace_id: UUID,
    body: SettingsPatch,
    user: User = Depends(get_current_user),
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not row:
        row = WorkspaceSettings(workspace_id=workspace_id)
        db.add(row)
    if body.timezone:
        row.timezone = body.timezone
    if body.retention_days is not None:
        row.retention_days = body.retention_days
    if body.owner_notify:
        notes = dict(row.notifications or {})
        owner = dict(notes.get("owner") or {})
        if body.owner_notify.email is not None:
            owner["email"] = body.owner_notify.email.strip()
        if body.owner_notify.phone is not None:
            owner["phone"] = body.owner_notify.phone.strip()
        if body.owner_notify.whatsapp is not None:
            owner["whatsapp"] = body.owner_notify.whatsapp.strip()
        notes["owner"] = owner
        row.notifications = notes
    db.commit()
    log_audit(db, workspace_id=workspace_id, actor_user_id=user.id, action="settings.updated", summary="Workspace settings")
    return {"timezone": row.timezone, "retention_days": row.retention_days}


@router.post("/workspace-settings/owner-notify/test")
def test_owner_notify_channel(
    workspace_id: UUID,
    body: OwnerNotifyTestBody,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    from app.config import get_settings as app_settings
    from app.services.owner_notify import (
        mark_channel_verified,
        owner_contact,
        send_test_notification,
    )

    row = db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not row:
        row = WorkspaceSettings(workspace_id=workspace_id)
        db.add(row)
    s = app_settings()
    owner = (row.notifications or {}).get("owner") if isinstance(row.notifications, dict) else {}
    owner = owner if isinstance(owner, dict) else {}
    contacts = owner_contact(owner, s)
    status, ch = send_test_notification(body.channel, settings=s, contacts=contacts)
    row.notifications = mark_channel_verified(row.notifications or {}, ch, status=status)
    db.commit()
    return {"channel": ch, "status": status}


@router.get("/audit-events")
def audit_events(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).limit(50)
    ).all()
    return [{"action": a.action, "summary": a.summary, "created_at": a.created_at} for a in rows]


@router.get("/notifications")
def notifications(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Notification).where(Notification.workspace_id == workspace_id).limit(50)
    ).all()
    return [{"id": n.id, "title": n.title, "body": n.body, "read": n.read} for n in rows]


# --- Developers / ingress ---
@router.get("/developers/ingress")
def get_ingress(
    workspace_id: UUID,
    _m: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(IngressIntegration).where(IngressIntegration.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not row:
        secret = secrets.token_urlsafe(24)
        row = IngressIntegration(
            workspace_id=workspace_id,
            name="default",
            secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {
            "integration_id": row.id,
            "endpoint": f"/v1/ingress/{row.id}/leads",
            "secret": secret,
        }
    return {
        "integration_id": row.id,
        "endpoint": f"/v1/ingress/{row.id}/leads",
        "secret": "(rotate to reveal — create new integration in future)",
    }