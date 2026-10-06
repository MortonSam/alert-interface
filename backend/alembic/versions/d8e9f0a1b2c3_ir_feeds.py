"""Investor-relations feeds per ticker: where a company's own press releases can be read, found once, dated when they last answered.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
"""
from alembic import op
import sqlalchemy as sa

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ir_feeds",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("domain", sa.Text(), nullable=True),             # the company's web domain, from its Intrinio profile
        sa.Column("feed_url", sa.Text(), nullable=True),           # the first feed that answered with items; null when none did
        sa.Column("kind", sa.String(20), nullable=True),           # rss | atom
        sa.Column("items", sa.Integer(), nullable=True),           # items the feed held when found
        sa.Column("probed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ir_feeds")
