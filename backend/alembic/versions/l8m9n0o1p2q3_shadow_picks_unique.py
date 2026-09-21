"""Add eval_date to shadow_picks, unique constraints for idempotency.

shadow_picks: The same earnings event is evaluated on multiple nights,
so the key must include the evaluation date. Adds eval_date (backfilled
from decided_at in US Eastern), keys on (symbol, event_date, eval_date).
Only deletes same-day repeats (same eval_date), preserves multi-night
history.

credit_shadow_picks: One condor per event_date. Keeps the EARLIEST row
(matching on_conflict_do_nothing semantics), deletes later duplicates.

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "l8m9n0o1p2q3"
down_revision = "k7l8m9n0o1p2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add eval_date column, backfill from decided_at in US Eastern
    op.add_column(
        "shadow_picks",
        sa.Column("eval_date", sa.Date, nullable=True),
    )
    op.execute(sa.text("""
        UPDATE shadow_picks
        SET eval_date = (decided_at AT TIME ZONE 'America/New_York')::date
    """))
    op.alter_column("shadow_picks", "eval_date", nullable=False)

    # 2. Delete same-day repeats only (keep latest decided_at per group)
    op.execute(sa.text("""
        DELETE FROM shadow_picks
        WHERE id NOT IN (
            SELECT DISTINCT ON (symbol, event_date, eval_date) id
            FROM shadow_picks
            ORDER BY symbol, event_date, eval_date, decided_at DESC
        )
    """))

    # 3. Unique constraint on (symbol, event_date, eval_date)
    op.create_unique_constraint(
        "uq_shadow_picks_symbol_event_eval",
        "shadow_picks",
        ["symbol", "event_date", "eval_date"],
    )

    # 4. credit_shadow_picks: keep earliest row per (symbol, event_date)
    op.execute(sa.text("""
        DELETE FROM credit_shadow_picks
        WHERE id NOT IN (
            SELECT DISTINCT ON (symbol, event_date) id
            FROM credit_shadow_picks
            ORDER BY symbol, event_date, decided_at ASC
        )
    """))

    op.create_unique_constraint(
        "uq_credit_shadow_picks_symbol_event_date",
        "credit_shadow_picks",
        ["symbol", "event_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_credit_shadow_picks_symbol_event_date", "credit_shadow_picks")
    op.drop_constraint("uq_shadow_picks_symbol_event_eval", "shadow_picks")
    op.drop_column("shadow_picks", "eval_date")
