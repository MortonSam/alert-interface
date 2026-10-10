"""Ivy's one-sentence explanations on Discover (behind DISCOVER_NEWS_ENABLED): news_stories gains each story's summary (her input
alongside the headline), and ivy_move_notes stores each sentence with its sources, the check result and when it was written,
keyed by the stock and a fingerprint of the stories she read, so a sentence is written again only when those stories change.

Revision ID: c193d1e1cd44
Revises: c8d9e0f1a2b3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c193d1e1cd44"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_stories", sa.Column("summary", sa.Text(), nullable=True))
    op.create_table(
        "ivy_move_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),        # the stories she read (services/ivy_moves.fingerprint)
        sa.Column("move_pct", sa.Numeric(10, 4), nullable=True),        # the printed change she was given
        sa.Column("sentence", sa.Text(), nullable=True),                # null when the row falls back to the headline display
        sa.Column("result", sa.String(16), nullable=False),             # "passed" | "no_news" | "fallback"
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),   # the stories that informed her, lead first
        sa.Column("problems", postgresql.JSONB(), nullable=False, server_default="[]"),  # why a draft failed the check, per attempt
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 5), nullable=True),
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", "fingerprint", name="uq_ivy_move_notes_symbol_fingerprint"),
    )


def downgrade() -> None:
    op.drop_table("ivy_move_notes")
    op.drop_column("news_stories", "summary")
