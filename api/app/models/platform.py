from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import (
    CallDirection,
    CallOutcome,
    CampaignStatus,
    KnowledgeStatus,
    LeadStatus,
    LedgerEntryType,
    PhoneNumberStatus,
    WebhookDeliveryStatus,
)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[KnowledgeStatus] = mapped_column(String(32), default=KnowledgeStatus.ready)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("workspace_id", "phone_e164", name="uq_lead_phone"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_e164: Mapped[str] = mapped_column(String(32))
    status: Mapped[LeadStatus] = mapped_column(String(32), default=LeadStatus.eligible)
    consent_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    qualification: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    interest_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[str | None] = mapped_column(String(128), nullable=True)
    follow_up_required: Mapped[bool] = mapped_column(Boolean, default=False)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuppressionRecord(Base):
    __tablename__ = "suppression_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    phone_e164: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    e164: Mapped[str] = mapped_column(String(32))
    status: Mapped[PhoneNumberStatus] = mapped_column(String(32), default=PhoneNumberStatus.pending)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    inbound_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True
    )
    balance_paise: Mapped[int] = mapped_column(Integer, default=5000)
    reserved_paise: Mapped[int] = mapped_column(Integer, default=0)


class WalletLedgerEntry(Base):
    __tablename__ = "wallet_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(String(32))
    amount_paise: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(String(128), unique=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    outpero_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    direction: Mapped[CallDirection] = mapped_column(String(16))
    outcome: Mapped[CallOutcome] = mapped_column(String(32), default=CallOutcome.queued)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider_call_sid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    livekit_room: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CallRequest(Base):
    __tablename__ = "call_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_call_request_idem"),
    )


class IngressIntegration(Base):
    __tablename__ = "ingress_integrations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    secret_hash: Mapped[str] = mapped_column(String(128))
    default_employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[CampaignStatus] = mapped_column(String(32), default=CampaignStatus.draft)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CampaignRecipient(Base):
    __tablename__ = "campaign_recipients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    signing_secret: Mapped[str] = mapped_column(String(128))
    events: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(String(32), default=WebhookDeliveryStatus.pending)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    integration_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="connected")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceSettings(Base):
    __tablename__ = "workspace_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True
    )
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    notifications: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())