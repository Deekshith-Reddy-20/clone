"""Outpero Phase-1 inbound call import connections

Revision ID: 20261121_0010
Revises: 20261120_0009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261121_0010"
down_revision: Union[str, None] = "20261120_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outpero_inbound_connections",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("connection_key", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outpero_agent_id", sa.Uuid(), sa.ForeignKey("outpero_agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_slug", sa.String(length=128), nullable=False),
        sa.Column("did_e164", sa.String(length=32), nullable=False),
        sa.Column("signing_secret", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("phase", sa.String(length=64), nullable=False, server_default="inbound_call_import_v1"),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("connection_key", name="uq_outpero_inbound_connection_key"),
    )
    op.create_index("ix_outpero_inbound_connections_workspace_id", "outpero_inbound_connections", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_outpero_inbound_connections_workspace_id", table_name="outpero_inbound_connections")
    op.drop_table("outpero_inbound_connections")
