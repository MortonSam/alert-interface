"""Market values (Sam, 2026-11-10): one row per active stock, the company's market value from the cover page of its latest 10-Q or
10-K (each share class times its own licensed close, services/market_value), dated by the cover and the close it used. value is
null while the company is on the hold-out list or cannot be worked out, and held_reason says why. Two symbols of one company
(GOOG and GOOGL) carry the same figure under one company key.

Revision ID: c3e5a7b9d1f2
Revises: a1c2c0d9e7f5 (accounts, in the launch candidate)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3e5a7b9d1f2"
down_revision = "a1c2c0d9e7f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_values",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("company", sa.String(10), nullable=False, index=True),
        sa.Column("value", sa.Numeric(20, 2), nullable=True),
        sa.Column("held_reason", sa.Text, nullable=True),
        sa.Column("shares", sa.Numeric(20, 2), nullable=True),
        sa.Column("classes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("shares_as_of", sa.Date, nullable=True),
        sa.Column("close_date", sa.Date, nullable=True),
        sa.Column("accession", sa.String(25), nullable=True),
        sa.Column("form", sa.String(10), nullable=True),
        sa.Column("filed", sa.Date, nullable=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_values")
