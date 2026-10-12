"""pricing_verdicts: Ivy v3's ledger of verdicts, one row per stock and report, settled after the report (services/pricing_desk).

Revision ID: d0e1f2a3b4c5
Revises: be829f590ead
Create Date: 2026-10-12
"""
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "be829f590ead"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS pricing_verdicts (
        id UUID PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        report_date DATE NOT NULL,
        computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        computation_version SMALLINT NOT NULL,
        verdict VARCHAR(20) NOT NULL,
        verdict_structure VARCHAR(20),
        ev_long_call NUMERIC(10, 2),
        ev_long_straddle NUMERIC(10, 2),
        ev_bull_call_spread NUMERIC(10, 2),
        ev_iron_condor NUMERIC(10, 2),
        legs JSONB NOT NULL DEFAULT '{}'::jsonb,
        settled_at TIMESTAMPTZ,
        actual_move_pct NUMERIC(8, 4),
        settled_long_call NUMERIC(10, 2),
        settled_long_straddle NUMERIC(10, 2),
        settled_bull_call_spread NUMERIC(10, 2),
        settled_iron_condor NUMERIC(10, 2),
        CONSTRAINT uq_pricing_verdicts_symbol_report UNIQUE (symbol, report_date)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pricing_verdicts_symbol ON pricing_verdicts (symbol)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pricing_verdicts_report_date ON pricing_verdicts (report_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pricing_verdicts")
