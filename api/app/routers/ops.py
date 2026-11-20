from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.database import get_db
from app.models import User, Workspace
from app.services.telephony import telephony_status_payload

router = APIRouter(prefix="/v1/ops", tags=["ops"])


@router.get("/status")
def ops_status(db: Session = Depends(get_db)) -> dict:
    workspaces = db.scalar(select(func.count()).select_from(Workspace)) or 0
    telephony = telephony_status_payload()
    return {
        "workspaces": workspaces,
        "voice_runtime": telephony["mode"],
        "queue": "inline",
        "telephony": telephony,
    }


@router.post("/workspaces/{workspace_id}/suspend")
def suspend_workspace(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not user.email.endswith("@karyuk.ops") and user.email != "ops@karyuk.local":
        raise HTTPException(status_code=403, detail="Operator access required")
    return {"workspace_id": workspace_id, "suspended": True, "actor": user.email}