from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.jwt_dev import is_dev_token_valid
from app.auth.keycloak import decode_keycloak_token
from app.config import Settings, get_settings
from app.database import get_db
from app.models import Membership, User

bearer = HTTPBearer(auto_error=False)


def get_request_id(request: Request) -> str:
    return request.headers.get("x-request-id", request.state.request_id if hasattr(request.state, "request_id") else "local")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = credentials.credentials
    claims: dict | None = None

    if settings.keycloak_enabled:
        claims = decode_keycloak_token(settings, token)
        if not claims:
            raise HTTPException(status_code=401, detail="Invalid token")
        sub = claims.get("sub")
        iss = claims.get("iss", settings.keycloak_issuer)
        email = claims.get("email") or claims.get("preferred_username")
        name = claims.get("name") or email
        if not sub or not email:
            raise HTTPException(status_code=401, detail="Invalid token claims")
        user = db.execute(
            select(User).where(User.keycloak_sub == sub, User.keycloak_issuer == iss)
        ).scalar_one_or_none()
        if not user:
            user = User(
                keycloak_sub=sub,
                keycloak_issuer=iss,
                email=str(email).lower(),
                display_name=str(name),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    if settings.dev_auth_enabled:
        claims = is_dev_token_valid(settings, token)
        if not claims:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token claims")
        user = db.get(User, UUID(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    raise HTTPException(status_code=503, detail="Authentication is not configured")


def get_workspace_membership(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Membership:
    membership = db.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user.id,
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return membership