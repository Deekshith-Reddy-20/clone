"""V-Farms availability activity for Live inbound Calls."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261122_0012"
down_revision = "20261121_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vfarms_availability_activity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="checking"),
        sa.Column("correlation", sa.String(48), nullable=False, server_default="independent"),
        sa.Column("provider_call_id", sa.String(128), nullable=True),
        sa.Column("associated_call_id", sa.Uuid(), nullable=True),
        sa.Column("quote_ref", sa.String(64), nullable=True),
        sa.Column("check_in", sa.String(10), nullable=True),
        sa.Column("check_out", sa.String(10), nullable=True),
        sa.Column("guest_count", sa.Integer(), nullable=True),
        sa.Column("total_inr", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_vfarms_availability_activity_workspace_id", "vfarms_availability_activity", ["workspace_id"])
    op.create_index(
        "ix_vfarms_availability_activity_provider_call_id",
        "vfarms_availability_activity",
        ["provider_call_id"],
    )
    op.create_index(
        "ix_vfarms_availability_activity_associated_call_id",
        "vfarms_availability_activity",
        ["associated_call_id"],
    )


def downgrade() -> None:
    op.drop_table("vfarms_availability_activity")
