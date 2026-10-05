"""Company profiles from Intrinio, stored nightly with their date; one earnings event per ticker and date.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7

The unique index on earnings events is created only when no duplicates exist; a database that still holds
duplicates gets it from scripts/dedupe_earnings_events --write, and validate errors until it is there.
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("industry_category", sa.Text(), nullable=True),
        sa.Column("industry_group", sa.Text(), nullable=True),
        sa.Column("employees", sa.Integer(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("latest_filing_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="intrinio"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM events WHERE event_type = 'earnings' GROUP BY ticker_id, event_date HAVING count(*) > 1) THEN
            CREATE UNIQUE INDEX IF NOT EXISTS uq_events_earnings_ticker_date ON events (ticker_id, event_date) WHERE event_type = 'earnings';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_events_earnings_ticker_date")
    op.drop_table("company_profiles")
