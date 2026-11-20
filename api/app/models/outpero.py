from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OutperoAgent(Base):
    """Local registry of Outpero AI employees (slug + secrets).

    Outpero has no public agent-list API; operators register each employee here
    using the Instant Leads slug and X-Outpero-Lead-Secret from Outpero.
    """

    __tablename__ = "outpero_agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_outpero_agent_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(128))
    lead_secret: Mapped[str] = mapped_column(String(255))
    webhook_signing_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    schema_cache: Mapped[dict] = mapped_column(JSON, default=dict)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_schema_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OutperoWebhookEvent(Base):
    """Idempotent store for inbound Outpero webhook deliveries."""

    __tablename__ = "outpero_webhook_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "event_key", name="uq_outpero_event_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    outpero_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    event_key: Mapped[str] = mapped_column(String(191))
    external_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), default="call.ended")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="received")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutperoSyncLog(Base):
    __tablename__ = "outpero_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    outpero_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
