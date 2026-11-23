from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_workspace_membership
from app.database import get_db
from app.models import Membership, User
from app.models.enums import MembershipRole
from app.schemas.workspace import InviteAcceptResponse, InviteCreate, InviteOut, WorkspaceCreate, WorkspaceOut
from app.services.workspaces import accept_invite, create_invite, create_workspace_for_user, list_workspaces_for_user

router = APIRouter(prefix="/v1", tags=["workspaces"])


def _role_value(role: MembershipRole | str) -> str:
    return role.value if isinstance(role, MembershipRole) else str(role)


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkspaceOut]:
    return [
        WorkspaceOut(id=w.id, name=w.name, role=_role_value(role), created_at=w.created_at)
        for w, role in list_workspaces_for_user(db, user.id)
    ]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    workspace, membership = create_workspace_for_user(db, user=user, workspace_name=body.name)
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        role=_role_value(membership.role),
        created_at=workspace.created_at,
    )


@router.post("/workspaces/{workspace_id}/invites", response_model=InviteOut, status_code=201)
def create_workspace_invite(
    workspace_id: UUID,
    body: InviteCreate,
    membership: Membership = Depends(get_workspace_membership),
    db: Session = Depends(get_db),
) -> InviteOut:
    if membership.role not in (MembershipRole.owner, MembershipRole.admin):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        role = MembershipRole(body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid role") from exc
    invite, raw = create_invite(db, workspace_id=workspace_id, email=body.email, role=role)
    return InviteOut(
        id=invite.id,
        email=invite.email,
        expires_at=invite.expires_at,
        invite_token=raw,
    )


@router.post("/invites/{token}/accept", response_model=InviteAcceptResponse)
def accept_invite_token(
    token: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InviteAcceptResponse:
    try:
        membership = accept_invite(db, token=token, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InviteAcceptResponse(
        workspace_id=membership.workspace_id,
        message="Invite accepted",
    )