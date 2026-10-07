"""ir_feeds.classification: which found feeds are press-release feeds the calendar may read (press_releases), and which are
site blogs (blog), placeholder feeds (placeholder) or not yet reviewed (unreviewed). The 26 site-wide /feed hits of the
2026-10-06 discovery were reviewed by hand: six press-release feeds and one mixed feed stay readable, sixteen blogs and
three "Hello world!" placeholders are excluded.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
"""
from alembic import op
import sqlalchemy as sa

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None

BLOGS = ("APA", "CCL", "COO", "FRT", "KR", "OMC", "PKG", "PPL", "PSX", "TDG", "TER", "TPR", "UHS", "VICI", "VST", "XOM")
PLACEHOLDERS = ("FOX", "FOXA", "RCL")
PRESS = ("CRH", "DVA", "KDP", "NWS", "NWSA", "STLD", "WMB")


def upgrade() -> None:
    op.add_column("ir_feeds", sa.Column("classification", sa.String(20), nullable=True))
    op.execute("UPDATE ir_feeds SET classification = 'press_releases' WHERE feed_url IS NOT NULL")
    op.execute("UPDATE ir_feeds SET classification = 'blog' WHERE symbol IN (" + ", ".join(f"'{s}'" for s in BLOGS) + ") AND feed_url LIKE '%/feed'")
    op.execute("UPDATE ir_feeds SET classification = 'placeholder' WHERE symbol IN (" + ", ".join(f"'{s}'" for s in PLACEHOLDERS) + ") AND feed_url LIKE '%/feed'")
    op.execute("UPDATE ir_feeds SET classification = 'press_releases' WHERE symbol IN (" + ", ".join(f"'{s}'" for s in PRESS) + ") AND feed_url LIKE '%/feed'")


def downgrade() -> None:
    op.drop_column("ir_feeds", "classification")
