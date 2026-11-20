"""employee draft Sarvam TTS speaker

Revision ID: 20260319_0005
Revises: 20260318_0004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260319_0005"
down_revision: Union[str, None] = "20260318_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employee_drafts",
        sa.Column("tts_speaker", sa.String(length=32), nullable=False, server_default="shubh"),
    )


def downgrade() -> None:
    op.drop_column("employee_drafts", "tts_speaker")