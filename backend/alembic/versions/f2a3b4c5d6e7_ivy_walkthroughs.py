"""ivy_walkthroughs and ivy_compare_stories: Ivy's stock walkthrough, rebuilt nightly (services/walkthrough, scripts/build_walkthroughs).

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ivy_walkthroughs",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("facts_fingerprint", sa.String(32), nullable=False),
        sa.Column("story_fingerprint", sa.String(32), nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("sources", JSONB, nullable=False, server_default="{}"),
        sa.Column("story", JSONB, nullable=False, server_default="{}"),
        sa.Column("steps_shown", sa.Integer, nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ivy_compare_stories",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("other", sa.String(10), primary_key=True),
        sa.Column("fingerprint", sa.String(32), nullable=False),
        sa.Column("sentence", sa.Text, nullable=True),
        sa.Column("verdicts", JSONB, nullable=False, server_default="{}"),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ivy_compare_stories")
    op.drop_table("ivy_walkthroughs")
