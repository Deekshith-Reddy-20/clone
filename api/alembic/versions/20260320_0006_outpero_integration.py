"""Outpero voice agent integration

Revision ID: 20260320_0006
Revises: 20260319_0005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260320_0006"
down_revision: Union[str, None] = "20260319_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("company", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("lead_source", sa.String(length=64), nullable=True))
    op.add_column("leads", sa.Column("qualification", sa.String(length=64), nullable=True))
    op.add_column("leads", sa.Column("interest_level", sa.String(length=64), nullable=True))
    op.add_column("leads", sa.Column("requirements", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("budget", sa.String(length=128), nullable=True))
    op.add_column(
        "leads",
        sa.Column("follow_up_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("leads", sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "leads",
        sa.Column("profile", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column("leads", sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_leads_lead_source", "leads", ["lead_source"])
    op.create_index("ix_leads_qualification", "leads", ["qualification"])

    op.add_column("calls", sa.Column("outpero_agent_id", sa.Uuid(), nullable=True))
    op.add_column("calls", sa.Column("recording_url", sa.String(length=2048), nullable=True))
    op.add_column("calls", sa.Column("disposition", sa.String(length=64), nullable=True))
    op.add_column("calls", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calls", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "calls",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_calls_outpero_agent_id", "calls", ["outpero_agent_id"])
    op.create_index("ix_calls_lead_id", "calls", ["lead_id"])
    op.create_index("ix_calls_provider", "calls", ["provider"])
    op.create_index("ix_calls_disposition", "calls", ["disposition"])

    op.create_table(
        "outpero_agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("lead_secret", sa.String(length=255), nullable=False),
        sa.Column("webhook_signing_secret", sa.String(length=255), nullable=True),
        sa.Column("action_secret", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("schema_cache", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_schema_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_outpero_agent_slug"),
    )
    op.create_index("ix_outpero_agents_workspace_id", "outpero_agents", ["workspace_id"])

    op.create_table(
        "outpero_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("outpero_agent_id", sa.Uuid(), nullable=True),
        sa.Column("event_key", sa.String(length=191), nullable=False),
        sa.Column("external_call_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "event_key", name="uq_outpero_event_key"),
    )
    op.create_index("ix_outpero_webhook_events_workspace_id", "outpero_webhook_events", ["workspace_id"])
    op.create_index("ix_outpero_webhook_events_agent", "outpero_webhook_events", ["outpero_agent_id"])
    op.create_index("ix_outpero_webhook_events_external", "outpero_webhook_events", ["external_call_id"])

    op.create_table(
        "outpero_sync_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("outpero_agent_id", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outpero_sync_logs_workspace_id", "outpero_sync_logs", ["workspace_id"])
    op.create_index("ix_outpero_sync_logs_agent", "outpero_sync_logs", ["outpero_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_outpero_sync_logs_agent", table_name="outpero_sync_logs")
    op.drop_index("ix_outpero_sync_logs_workspace_id", table_name="outpero_sync_logs")
    op.drop_table("outpero_sync_logs")

    op.drop_index("ix_outpero_webhook_events_external", table_name="outpero_webhook_events")
    op.drop_index("ix_outpero_webhook_events_agent", table_name="outpero_webhook_events")
    op.drop_index("ix_outpero_webhook_events_workspace_id", table_name="outpero_webhook_events")
    op.drop_table("outpero_webhook_events")

    op.drop_index("ix_outpero_agents_workspace_id", table_name="outpero_agents")
    op.drop_table("outpero_agents")

    op.drop_index("ix_calls_disposition", table_name="calls")
    op.drop_index("ix_calls_provider", table_name="calls")
    op.drop_index("ix_calls_lead_id", table_name="calls")
    op.drop_index("ix_calls_outpero_agent_id", table_name="calls")
    op.drop_column("calls", "is_test")
    op.drop_column("calls", "ended_at")
    op.drop_column("calls", "started_at")
    op.drop_column("calls", "disposition")
    op.drop_column("calls", "recording_url")
    op.drop_column("calls", "outpero_agent_id")

    op.drop_index("ix_leads_qualification", table_name="leads")
    op.drop_index("ix_leads_lead_source", table_name="leads")
    op.drop_column("leads", "updated_at")
    op.drop_column("leads", "last_interaction_at")
    op.drop_column("leads", "profile")
    op.drop_column("leads", "next_follow_up_at")
    op.drop_column("leads", "follow_up_required")
    op.drop_column("leads", "budget")
    op.drop_column("leads", "requirements")
    op.drop_column("leads", "interest_level")
    op.drop_column("leads", "qualification")
    op.drop_column("leads", "lead_source")
    op.drop_column("leads", "location")
    op.drop_column("leads", "company")
    op.drop_column("leads", "email")
