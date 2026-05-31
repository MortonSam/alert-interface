"""Add theses table for structured bet / thesis tracking

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-05-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE thesis_direction_enum AS ENUM ('bullish', 'bearish', 'neutral')")
    op.execute("CREATE TYPE thesis_status_enum AS ENUM ('open', 'resolved', 'needs_manual_resolution')")
    op.execute("CREATE TYPE self_grade_enum AS ENUM ('right', 'right_for_wrong_reasons', 'wrong')")

    op.create_table(
        "theses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        # Bet fields
        sa.Column("direction", postgresql.ENUM(name="thesis_direction_enum", create_type=False), nullable=False),
        sa.Column("conviction", sa.SmallInteger(), nullable=False),
        sa.Column("catalyst", sa.Text()),
        sa.Column("price_target", sa.Numeric(12, 4)),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 4)),  # captured from live quote at creation
        sa.Column("reasoning", sa.Text()),
        # Status
        sa.Column("status", postgresql.ENUM(name="thesis_status_enum", create_type=False), nullable=False, server_default="open"),
        # Resolution fields
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("price_at_resolution", sa.Numeric(12, 4)),
        sa.Column("direction_correct", sa.Boolean()),
        sa.Column("target_reached", sa.Boolean()),
        sa.Column("self_grade", postgresql.ENUM(name="self_grade_enum", create_type=False)),
        sa.Column("reflection", sa.Text()),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_theses_ticker_id", "theses", ["ticker_id"])
    op.create_index("ix_theses_status", "theses", ["status"])
    op.create_index("ix_theses_target_date", "theses", ["target_date"])


def downgrade() -> None:
    op.drop_table("theses")
    op.execute("DROP TYPE IF EXISTS self_grade_enum")
    op.execute("DROP TYPE IF EXISTS thesis_status_enum")
    op.execute("DROP TYPE IF EXISTS thesis_direction_enum")
