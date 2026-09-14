"""Add season and receipt to alert_picks.

Revision ID: p8q6l3m4n5o6
Revises: o7p5k2l3m4n5
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "p8q6l3m4n5o6"
down_revision = "o7p5k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_picks", sa.Column("season", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("alert_picks", sa.Column("receipt", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_picks", "receipt")
    op.drop_column("alert_picks", "season")
