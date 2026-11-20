"""Voice booking requests (pending staff confirmation)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VoiceBookingRequest(Base):
    __tablename__ = "voice_booking_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_staff", index=True)
    caller_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notify_status: Mapped[str] = mapped_column(String(32), default="stub_pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())