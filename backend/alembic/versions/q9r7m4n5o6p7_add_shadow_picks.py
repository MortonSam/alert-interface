"""Add shadow_picks table.

Revision ID: q9r7m4n5o6p7
Revises: p8q6l3m4n5o6
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "q9r7m4n5o6p7"
down_revision = "p8q6l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_picks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False, index=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("probability", sa.Numeric(6, 4), nullable=False),
        sa.Column("threshold_used", sa.Numeric(4, 2), nullable=False),
        sa.Column("would_pick", sa.Boolean(), nullable=False),
        sa.Column("top_factors", JSONB(), nullable=True),
        sa.Column("v2_decision", sa.String(30), nullable=True),
        sa.Column("v2_pick_id", UUID(as_uuid=True), sa.ForeignKey("alert_picks.id"), nullable=True),
        sa.Column("actual_5d", sa.Numeric(8, 4), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_shadow_picks_event_date", "shadow_picks", ["event_date"])


def downgrade() -> None:
    op.drop_index("ix_shadow_picks_event_date")
    op.drop_table("shadow_picks")
