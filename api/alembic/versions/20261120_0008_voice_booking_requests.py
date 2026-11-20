"""voice_booking_requests table."""

from alembic import op
import sqlalchemy as sa

revision = "20261120_0008"
down_revision = "20261120_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_booking_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_staff"),
        sa.Column("caller_phone", sa.String(32), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("notify_status", sa.String(32), nullable=False, server_default="stub_pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_booking_requests_workspace_id", "voice_booking_requests", ["workspace_id"])
    op.create_index("ix_voice_booking_requests_call_id", "voice_booking_requests", ["call_id"])
    op.create_index("ix_voice_booking_requests_status", "voice_booking_requests", ["status"])


def downgrade() -> None:
    op.drop_table("voice_booking_requests")