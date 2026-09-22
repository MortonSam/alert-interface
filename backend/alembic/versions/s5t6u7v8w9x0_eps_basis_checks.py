"""eps_basis_checks: each stored earnings actual checked against EDGAR XBRL diluted EPS.

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s5t6u7v8w9x0"
down_revision = "r4s5t6u7v8w9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eps_basis_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("stored_actual", sa.Numeric(10, 4), nullable=False),
        sa.Column("xbrl_eps", sa.Numeric(10, 4)),
        sa.Column("xbrl_tag", sa.String(40)),
        sa.Column("xbrl_period_end", sa.Date),
        sa.Column("match_status", sa.String(16), nullable=False),
        sa.Column("split_factor", sa.Numeric(8, 4)),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker_id", "event_date", name="uq_eps_basis_checks_ticker_event"),
    )
    op.create_index("ix_eps_basis_checks_status", "eps_basis_checks", ["match_status"])


def downgrade() -> None:
    op.drop_index("ix_eps_basis_checks_status", table_name="eps_basis_checks")
    op.drop_table("eps_basis_checks")
