from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import CallMode


class EmployeeCreate(BaseModel):
    brief: str = Field(min_length=12)
    language: str = Field(default="English", max_length=64)
    natural_spoken: bool = True
    mode: CallMode = CallMode.instant
    tts_speaker: str = Field(default="shubh", max_length=32)


class EmployeeDraftUpdate(BaseModel):
    brief: str | None = Field(default=None, min_length=12)
    operator_instructions: str | None = Field(default=None, max_length=12_000)
    business_profile: dict | None = None
    persona: dict | None = None
    language: str | None = Field(default=None, max_length=64)
    natural_spoken: bool | None = None
    mode: CallMode | None = None
    website_url: str | None = Field(default=None, max_length=2048)
    website_knowledge: str | None = Field(default=None, max_length=24_000)
    tts_speaker: str | None = Field(default=None, max_length=32)
    revision: int | None = None


class WebsiteAnalyzeRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class WebsiteAnalyzeResponse(BaseModel):
    website_url: str
    website_knowledge: str
    revision: int


class VoicePreviewCreate(BaseModel):
    speaker: str = Field(default="shubh", max_length=64)


class VoicePreviewVoiceOut(BaseModel):
    id: str
    label: str
    gender: str
    hint: str


class VoicePreviewSessionOut(BaseModel):
    call_id: UUID
    speaker: str
    websocket_path: str
    worker_build_sha: str = ""
    employee_snapshot_revision: str = ""
    employee_version_number: str = ""
    speech_stack: str = "sarvam"
    knowledge_state: str = "published"
    published_speaker: str = ""
    published_mode: str = ""
    preview_path: str = (
        "browser_preview: draft employee settings over WSS (Saaras v4 + Bulbul v4 Flash); "
        "live Exotel uses published snapshot for the assigned number"
    )
    knowledge_chars: int = 0
    sarvam_ready: bool = True
    sarvam_status: str = ""


class EmployeePublishedSnapshotOut(BaseModel):
    version_number: int
    snapshot_revision: int
    brief: str
    language: str
    natural_spoken: bool
    mode: CallMode
    tts_speaker: str
    website_url: str | None = None
    knowledge_chars: int = 0
    brief_chars: int = 0
    website_knowledge_chars: int = 0
    workspace_knowledge_chars: int = 0


class EmployeeInboundReadinessOut(BaseModel):
    published: bool
    assigned_numbers: list[str]
    can_receive_inbound: bool


class EmployeeDraftOut(BaseModel):
    revision: int
    brief: str
    operator_instructions: str = ""
    business_profile: dict | None = None
    persona: dict | None = None
    profile_warnings: list[str] = Field(default_factory=list)
    language: str
    natural_spoken: bool
    mode: CallMode
    tts_speaker: str = "shubh"
    website_url: str | None = None
    website_knowledge: str | None = None
    updated_at: datetime


class EmployeeOut(BaseModel):
    id: UUID
    workspace_id: UUID
    status: str
    active_version_id: UUID | None
    draft: EmployeeDraftOut | None
    published_snapshot: EmployeePublishedSnapshotOut | None = None
    inbound_readiness: EmployeeInboundReadinessOut | None = None
    created_at: datetime


class EmployeeVersionOut(BaseModel):
    id: UUID
    version_number: int
    snapshot: dict
    published_at: datetime