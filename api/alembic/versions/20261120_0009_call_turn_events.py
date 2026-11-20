"""call_turn_events for per-turn PSTN trace (30d retention)

Revision ID: 20261120_0009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_0009"
down_revision: Union[str, None] = "20261120_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "call_turn_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_turn_events_call_id", "call_turn_events", ["call_id"])
    op.create_index("ix_call_turn_events_workspace_id", "call_turn_events", ["workspace_id"])
    op.create_index("ix_call_turn_events_created_at", "call_turn_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_call_turn_events_created_at", table_name="call_turn_events")
    op.drop_index("ix_call_turn_events_workspace_id", table_name="call_turn_events")
    op.drop_index("ix_call_turn_events_call_id", table_name="call_turn_events")
    op.drop_table("call_turn_events")