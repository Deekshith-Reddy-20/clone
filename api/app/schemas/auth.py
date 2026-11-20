from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    workspaces: list["WorkspaceSummary"]


class WorkspaceSummary(BaseModel):
    id: UUID
    name: str
    role: str


MeResponse.model_rebuild()