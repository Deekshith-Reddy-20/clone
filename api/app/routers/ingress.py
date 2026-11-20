import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IngressIntegration, Lead
from app.models.enums import LeadStatus
from app.routers.platform import normalize_e164
from app.services.calls import simulate_outbound_call

router = APIRouter(prefix="/v1", tags=["ingress"])


class IngressLead(BaseModel):
    phone: str
    name: str | None = None
    employee_id: UUID | None = None


@router.post("/ingress/{integration_id}/leads", status_code=202)
def ingress_lead(
    integration_id: UUID,
    body: IngressLead,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    integration = db.get(IngressIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Unknown integration")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer secret")
    token = authorization.removeprefix("Bearer ").strip()
    if hashlib.sha256(token.encode()).hexdigest() != integration.secret_hash:
        raise HTTPException(status_code=401, detail="Invalid secret")

    e164 = normalize_e164(body.phone)
    lead = db.execute(
        select(Lead).where(
            Lead.workspace_id == integration.workspace_id,
            Lead.phone_e164 == e164,
        )
    ).scalar_one_or_none()
    if not lead:
        lead = Lead(
            workspace_id=integration.workspace_id,
            name=body.name,
            phone_e164=e164,
            status=LeadStatus.eligible,
            consent_source="webhook",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

    employee_id = body.employee_id or integration.default_employee_id
    if not employee_id:
        return {"lead_id": lead.id, "status": "accepted", "call_id": None}

    try:
        call = simulate_outbound_call(
            db,
            workspace_id=integration.workspace_id,
            employee_id=employee_id,
            lead_id=lead.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"lead_id": lead.id, "status": "completed", "call_id": call.id}