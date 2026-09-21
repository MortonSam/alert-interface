"""Store each backtest_v2 run so pages render real backtest numbers.

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q3r4s5t6u7v8"
down_revision = "p2q3r4s5t6u7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ivy_backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),            # latest event date in the features used
        sa.Column("momentum_cutoff_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("min_prior_quarters", sa.SmallInteger, nullable=False),
        sa.Column("folds", postgresql.JSONB, nullable=False),        # [{label, setups, hits, hit_rate, base_n, base_rate}]
        sa.Column("setups", sa.Integer, nullable=False),
        sa.Column("hits", sa.Integer, nullable=False),
        sa.Column("hit_rate", sa.Numeric(8, 6), nullable=False),
        sa.Column("base_n", sa.Integer, nullable=False),
        sa.Column("base_rate", sa.Numeric(8, 6), nullable=False),    # pooled over every earnings event in the test years
        sa.Column("passed", sa.Boolean, nullable=False),
    )
    op.create_index("ix_ivy_backtest_runs_run_at", "ivy_backtest_runs", ["run_at"])


def downgrade() -> None:
    op.drop_index("ix_ivy_backtest_runs_run_at", table_name="ivy_backtest_runs")
    op.drop_table("ivy_backtest_runs")
