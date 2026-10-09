"""pending_deals: tickers under a definitive cash acquisition, written only through scripts/set_pending_deal

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS pending_deals (
        id bigserial PRIMARY KEY,
        symbol text NOT NULL,
        security_record_id uuid,
        price_per_share numeric(12, 4) NOT NULL CHECK (price_per_share > 0),
        consideration text NOT NULL DEFAULT 'cash' CHECK (consideration = 'cash'),
        acquirer text NOT NULL,
        agreed_on date NOT NULL,
        expected_close text,
        filing_url text NOT NULL,
        filing_evidence text NOT NULL,
        filing_checked_at timestamptz NOT NULL,
        status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'terminated')),
        ended_on date,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_deals_active_symbol ON pending_deals (symbol) WHERE status = 'active'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_deals")
