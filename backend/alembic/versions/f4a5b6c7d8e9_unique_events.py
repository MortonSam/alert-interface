"""One event per ticker, type and date (analyst actions exempt): the dedupe runs first, then the unique index.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8

The dedupe is the same plan as scripts/dedupe_earnings_events --write (keep the richest row, carry over what it lacks,
repoint references). If any duplicate remains afterwards the migration raises and nothing is indexed.
"""
from alembic import op

from app.scripts.dedupe_earnings_events import INDEX_SQL, assert_no_duplicates, dedupe_sync

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    plans, _ = dedupe_sync(conn, write=True)
    for p in plans:
        print(f"  dedupe: {p['symbol']} {p['event_type']} {p['event_date']}: kept {p['keep']}, dropped {len(p['drop'])}, filled {p['fill'] or 'nothing'}")
    from sqlalchemy import text
    remaining = conn.execute(text("SELECT count(*) FROM (SELECT 1 FROM events WHERE event_type <> 'analyst_action' GROUP BY ticker_id, event_type, event_date HAVING count(*) > 1) d")).scalar() or 0
    assert_no_duplicates(remaining)
    op.execute("DROP INDEX IF EXISTS uq_events_earnings_ticker_date")
    op.execute(INDEX_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_events_ticker_type_date")
