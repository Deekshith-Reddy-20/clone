"""call telephony provider fields

Revision ID: 20260318_0003
Revises: 20260318_0002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260318_0003"
down_revision: Union[str, None] = "20260318_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("calls", sa.Column("provider_call_sid", sa.String(128), nullable=True))
    op.add_column("calls", sa.Column("livekit_room", sa.String(128), nullable=True))
    op.create_index("ix_calls_provider_call_sid", "calls", ["provider_call_sid"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_calls_provider_call_sid", table_name="calls")
    op.drop_column("calls", "livekit_room")
    op.drop_column("calls", "provider_call_sid")
    op.drop_column("calls", "provider")