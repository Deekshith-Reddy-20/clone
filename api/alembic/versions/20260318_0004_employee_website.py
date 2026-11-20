"""employee draft website fields

Revision ID: 20260318_0004
Revises: 20260318_0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260318_0004"
down_revision: Union[str, None] = "20260318_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employee_drafts", sa.Column("website_url", sa.String(length=2048), nullable=True))
    op.add_column("employee_drafts", sa.Column("website_knowledge", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("employee_drafts", "website_knowledge")
    op.drop_column("employee_drafts", "website_url")