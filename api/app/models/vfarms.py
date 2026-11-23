"""V-Farms stay quote + booking attempt persistence (voice actions)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VfarmsStayQuote(Base):
    __tablename__ = "vfarms_stay_quotes"
    __table_args__ = (UniqueConstraint("workspace_id", "quote_ref", name="uq_vfarms_quote_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    quote_ref: Mapped[str] = mapped_column(String(64))
    check_in: Mapped[str] = mapped_column(String(10))
    check_out: Mapped[str] = mapped_column(String(10))
    guest_count: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    total_inr: Mapped[int] = mapped_column(Integer)
    amount_due_now_inr: Mapped[int] = mapped_column(Integer, default=0)
    rate_per_night_inr: Mapped[int] = mapped_column(Integer, default=0)
    nights: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    source_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VfarmsAvailabilityActivity(Base):
    """Workspace-scoped availability-check lifecycle for Live inbound Calls.

    Does not store secrets or raw caller phone numbers. Correlation to a call is
    only via explicit provider_call_id / call_id resolution — never inferred.
    """

    __tablename__ = "vfarms_availability_activity"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(32), default="checking")
    # independent | linked | link_attempted_not_found
    correlation: Mapped[str] = mapped_column(String(48), default="independent")
    provider_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    associated_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    quote_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    check_in: Mapped[str | None] = mapped_column(String(10), nullable=True)
    check_out: Mapped[str | None] = mapped_column(String(10), nullable=True)
    guest_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VfarmsBookingAttempt(Base):
    __tablename__ = "vfarms_booking_attempts"
    __table_args__ = (UniqueConstraint("workspace_id", "attempt_key", name="uq_vfarms_attempt_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    attempt_key: Mapped[str] = mapped_column(String(96))
    quote_ref: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="started")
    vfarms_booking_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vfarms_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
