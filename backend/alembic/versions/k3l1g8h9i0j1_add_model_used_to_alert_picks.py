"""Add model_used to alert_picks.

Revision ID: k3l1g8h9i0j1
Revises: j2k0f7g8h9i0
Create Date: 2026-08-31

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "k3l1g8h9i0j1"
down_revision = "j2k0f7g8h9i0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_picks", sa.Column("model_used", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_picks", "model_used")
