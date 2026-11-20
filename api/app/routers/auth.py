from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.jwt_dev import create_access_token
from app.auth.passwords import verify_password
from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.schemas.auth import LoginRequest, MeResponse, RegisterRequest, TokenResponse, WorkspaceSummary
from app.services.workspaces import list_workspaces_for_user, register_with_password

router = APIRouter(prefix="/v1", tags=["auth"])


@router.post("/auth/register", response_model=TokenResponse)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.dev_auth_enabled or settings.keycloak_enabled:
        raise HTTPException(status_code=403, detail="Registration disabled")
    try:
        user, _workspace = register_with_password(
            db,
            name=body.name,
            email=body.email,
            password=body.password,
            workspace_name=body.workspace_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token, expires_in = create_access_token(settings, user_id=user.id, email=user.email)
    return TokenResponse(access_token=token, expires_in=expires_in)


DEV_AUTO_EMAIL = "dev@example.com"


@router.post("/auth/dev-session", response_model=TokenResponse)
def dev_session(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Local-only: mint a token for the fixed dev user (no password)."""
    if not settings.dev_auth_enabled or settings.keycloak_enabled:
        raise HTTPException(status_code=403, detail="Dev session disabled")
    if settings.app_env not in ("development", "local", "test"):
        raise HTTPException(status_code=403, detail="Dev session disabled")
    user = db.execute(select(User).where(User.email == DEV_AUTO_EMAIL.lower())).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=f"{DEV_AUTO_EMAIL} not found")
    token, expires_in = create_access_token(settings, user_id=user.id, email=user.email)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.dev_auth_enabled or settings.keycloak_enabled:
        raise HTTPException(status_code=403, detail="Login disabled")
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token, expires_in = create_access_token(settings, user_id=user.id, email=user.email)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    workspaces = [
        WorkspaceSummary(id=w.id, name=w.name, role=role.value)
        for w, role in list_workspaces_for_user(db, user.id)
    ]
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        workspaces=workspaces,
    )