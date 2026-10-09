"""finnhub_calls: one Finnhub request budget shared by every process (services/finnhub_limiter)

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
"""
from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS finnhub_calls (
        id bigserial PRIMARY KEY,
        at timestamptz NOT NULL DEFAULT clock_timestamp(),
        priority text NOT NULL)""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_finnhub_calls_at ON finnhub_calls (at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS finnhub_calls")
