from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "operator"


class InviteOut(BaseModel):
    id: UUID
    email: str
    expires_at: datetime
    invite_token: str


class InviteAcceptResponse(BaseModel):
    workspace_id: UUID
    message: str