import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.models import Invite, Membership, User, Workspace, WorkspaceSettings
from app.models.enums import MembershipRole
from app.services.wallet import ensure_wallet


def create_user_workspace(
    db: Session,
    *,
    email: str,
    display_name: str,
    workspace_name: str,
    password_hash: str | None,
    keycloak_issuer: str | None = None,
    keycloak_sub: str | None = None,
) -> tuple[User, Workspace, Membership]:
    user = User(
        email=email.lower(),
        display_name=display_name,
        password_hash=password_hash,
        keycloak_issuer=keycloak_issuer,
        keycloak_sub=keycloak_sub,
    )
    workspace = Workspace(name=workspace_name)
    db.add(user)
    db.add(workspace)
    db.flush()
    membership = Membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=MembershipRole.owner,
    )
    db.add(membership)
    db.flush()
    db.add(WorkspaceSettings(workspace_id=workspace.id))
    ensure_wallet(db, workspace.id)
    db.commit()
    db.refresh(user)
    db.refresh(workspace)
    db.refresh(membership)
    return user, workspace, membership


def create_workspace_for_user(db: Session, *, user: User, workspace_name: str) -> tuple[Workspace, Membership]:
    workspace = Workspace(name=workspace_name)
    db.add(workspace)
    db.flush()
    membership = Membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=MembershipRole.owner,
    )
    db.add(membership)
    db.flush()
    db.add(WorkspaceSettings(workspace_id=workspace.id))
    ensure_wallet(db, workspace.id)
    db.commit()
    db.refresh(workspace)
    db.refresh(membership)
    return workspace, membership


def list_workspaces_for_user(db: Session, user_id: UUID) -> list[tuple[Workspace, MembershipRole]]:
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(Workspace.created_at)
    ).all()
    return [(w, MembershipRole(r)) for w, r in rows]


def create_invite(
    db: Session,
    *,
    workspace_id: UUID,
    email: str,
    role: MembershipRole = MembershipRole.operator,
    ttl_hours: int = 72,
) -> tuple[Invite, str]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    invite = Invite(
        workspace_id=workspace_id,
        email=email.lower(),
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw_token


def accept_invite(db: Session, *, token: str, user: User) -> Membership:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    invite = db.execute(select(Invite).where(Invite.token_hash == token_hash)).scalar_one_or_none()
    if not invite or invite.accepted_at is not None:
        raise ValueError("Invalid or used invite")
    if invite.expires_at < datetime.now(UTC):
        raise ValueError("Invite expired")
    if user.email.lower() != invite.email.lower():
        raise ValueError("Invite email mismatch")

    existing = db.execute(
        select(Membership).where(
            Membership.workspace_id == invite.workspace_id,
            Membership.user_id == user.id,
        )
    ).scalar_one_or_none()
    if existing:
        invite.accepted_at = datetime.now(UTC)
        db.commit()
        return existing

    membership = Membership(
        workspace_id=invite.workspace_id,
        user_id=user.id,
        role=MembershipRole.operator,
    )
    invite.accepted_at = datetime.now(UTC)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def register_with_password(
    db: Session,
    *,
    name: str,
    email: str,
    password: str,
    workspace_name: str,
) -> tuple[User, Workspace]:
    existing = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if existing:
        raise ValueError("Email already registered")
    user, workspace, _ = create_user_workspace(
        db,
        email=email,
        display_name=name,
        workspace_name=workspace_name,
        password_hash=hash_password(password),
    )
    return user, workspace