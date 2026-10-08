"""growth_figures (quarterly revenue and GAAP diluted EPS against the same quarter a year earlier, stored only when two readers
agree) and growth_disagreements (every reading that did not agree, logged, never shown). Behind GROWTH_ENABLED.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_figures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("metric", sa.String(16), nullable=False),               # "revenue" | "eps"
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("year_ago_end", sa.Date(), nullable=True),
        sa.Column("value", sa.Numeric(20, 4), nullable=True),
        sa.Column("year_ago_value", sa.Numeric(20, 4), nullable=True),
        sa.Column("growth_pct", sa.Numeric(10, 2), nullable=True),        # null when the phrase is in words (a swing, from zero) or held
        sa.Column("phrase", sa.Text(), nullable=True),
        sa.Column("held_reason", sa.Text(), nullable=True),
        sa.Column("readers", sa.Text(), nullable=True),                   # which two readers agreed, for each of the two quarters
        sa.Column("tag", sa.String(120), nullable=True),                  # the XBRL tag the revenue came from
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", "metric", "period_end", name="uq_growth_symbol_metric_period"),
    )
    op.create_table(
        "growth_disagreements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("metric", sa.String(16), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("growth_disagreements")
    op.drop_table("growth_figures")
