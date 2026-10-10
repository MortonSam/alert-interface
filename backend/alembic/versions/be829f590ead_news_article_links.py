"""Discover links never depend on the vendor's redirect: each story stores the article URL its Finnhub link resolves to and where it
landed (link_state: "ok", "unchecked" (a bot check hid the page; the article URL is known), "paywall", "login" or "broken"), and when.

Revision ID: be829f590ead
Revises: c193d1e1cd44
"""
from alembic import op
import sqlalchemy as sa

revision = "be829f590ead"
down_revision = "c193d1e1cd44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_stories", sa.Column("article_url", sa.Text(), nullable=True))
    op.add_column("news_stories", sa.Column("link_state", sa.String(16), nullable=True))
    op.add_column("news_stories", sa.Column("link_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("news_stories", "link_checked_at")
    op.drop_column("news_stories", "link_state")
    op.drop_column("news_stories", "article_url")
