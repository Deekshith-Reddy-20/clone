from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import CallMode, EmployeeStatus


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[EmployeeStatus] = mapped_column(String(32), default=EmployeeStatus.draft)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployeeDraft(Base):
    __tablename__ = "employee_drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), unique=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    brief: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(64), default="English")
    natural_spoken: Mapped[bool] = mapped_column(default=True)
    mode: Mapped[CallMode] = mapped_column(String(32), default=CallMode.instant)
    website_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    website_knowledge: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_instructions: Mapped[str] = mapped_column(Text, default="")
    persona: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    business_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tts_speaker: Mapped[str] = mapped_column(String(32), default="shubh")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EmployeeVersion(Base):
    __tablename__ = "employee_versions"
    __table_args__ = (UniqueConstraint("employee_id", "version_number", name="uq_employee_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())