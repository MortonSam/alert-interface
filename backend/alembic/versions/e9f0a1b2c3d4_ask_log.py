"""Ask Ivy question log: every question asked in the free-text box, its normalized form and cache key, whether the stored
facts covered it, the verifier's verdict, the rendered answer, the model's token counts and estimated cost.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ask_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),           # symbol + normalized question + fact-pack fingerprint
        sa.Column("covered", sa.Boolean(), nullable=False),              # the stored facts covered the question
        sa.Column("verdict", sa.String(40), nullable=False),             # verified | partly_dropped | not_covered | rejected | cached | failed
        sa.Column("answer", postgresql.JSONB(), nullable=True),          # the rendered answer as served (data, inputs, as_of, rule)
        sa.Column("model", sa.String(40), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 5), nullable=True),         # estimated from services/research_cost prices
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ip_hash", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ask_log_cache_key", "ask_log", ["cache_key", "created_at"])
    op.create_index("ix_ask_log_symbol", "ask_log", ["symbol", "created_at"])


def downgrade() -> None:
    op.drop_table("ask_log")
