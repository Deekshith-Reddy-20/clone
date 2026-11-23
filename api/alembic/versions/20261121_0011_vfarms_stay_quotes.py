"""V-Farms stay quotes and booking attempts (staging voice actions)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261121_0011"
down_revision = "20261121_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vfarms_stay_quotes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quote_ref", sa.String(64), nullable=False),
        sa.Column("check_in", sa.String(10), nullable=False),
        sa.Column("check_out", sa.String(10), nullable=False),
        sa.Column("guest_count", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("total_inr", sa.Integer(), nullable=False),
        sa.Column("amount_due_now_inr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_per_night_inr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nights", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("source_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("workspace_id", "quote_ref", name="uq_vfarms_quote_ref"),
    )
    op.create_index("ix_vfarms_stay_quotes_workspace_id", "vfarms_stay_quotes", ["workspace_id"])

    op.create_table(
        "vfarms_booking_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_key", sa.String(96), nullable=False),
        sa.Column("quote_ref", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="started"),
        sa.Column("vfarms_booking_id", sa.String(64), nullable=True),
        sa.Column("vfarms_reference", sa.String(64), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("workspace_id", "attempt_key", name="uq_vfarms_attempt_key"),
    )
    op.create_index("ix_vfarms_booking_attempts_workspace_id", "vfarms_booking_attempts", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("vfarms_booking_attempts")
    op.drop_table("vfarms_stay_quotes")
