"""Add research_notes table

Revision ID: d4e5f6a7b8c9
Revises: c4d5e6f7a8b3
Create Date: 2026-05-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c4d5e6f7a8b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("source_filings", postgresql.JSONB, server_default="[]", nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("model_used", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("ticker_id", name="uq_research_notes_ticker"),
    )
    op.create_index("ix_research_notes_ticker_id", "research_notes", ["ticker_id"])


def downgrade() -> None:
    op.drop_index("ix_research_notes_ticker_id", table_name="research_notes")
    op.drop_table("research_notes")
