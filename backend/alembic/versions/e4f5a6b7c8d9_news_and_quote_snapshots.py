"""news_stories (Finnhub company and market headlines, the last 24 hours) and quote_snapshots (each S&P 500 stock's latest quote as
stored by the news step), for Discover's "Today's biggest movers" and "In the news" behind DISCOVER_NEWS_ENABLED.

Revision ID: e4f5a6b7c8d9
Revises: d2e4f5a6b7c8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e4f5a6b7c8d9"
down_revision = "d2e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source", sa.String(120), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("related", postgresql.ARRAY(sa.String(16)), nullable=False, server_default="{}"),
        sa.Column("category", sa.String(16), nullable=False),          # "company" | "general"
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_news_stories_published_at", "news_stories", ["published_at"])
    op.create_index("ix_news_stories_related", "news_stories", ["related"], postgresql_using="gin")
    op.create_table(
        "quote_snapshots",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("price", sa.Numeric(14, 4), nullable=True),
        sa.Column("change_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("prev_close", sa.Numeric(14, 4), nullable=True),
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=True),   # the last trade's time, from the quote
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("quote_snapshots")
    op.drop_index("ix_news_stories_related", table_name="news_stories")
    op.drop_index("ix_news_stories_published_at", table_name="news_stories")
    op.drop_table("news_stories")
