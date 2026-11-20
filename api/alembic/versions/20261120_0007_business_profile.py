"""Business profile columns on employee drafts + published snapshot."""

from alembic import op
import sqlalchemy as sa

revision = "20261120_0007"
down_revision = "20260320_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employee_drafts",
        sa.Column("operator_instructions", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("employee_drafts", sa.Column("persona", sa.JSON(), nullable=True))
    op.add_column("employee_drafts", sa.Column("business_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("employee_drafts", "business_profile")
    op.drop_column("employee_drafts", "persona")
    op.drop_column("employee_drafts", "operator_instructions")