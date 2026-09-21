"""Add eval_date to shadow_picks and credit_shadow_picks, unique per evaluation night.

Both tables re-evaluate the same earnings event on several nights, so the key
is (symbol, event_date, eval_date). eval_date is backfilled from decided_at in
US Eastern. Only same-day repeats are deleted; multi-night history is kept.

shadow_picks keeps the LATEST same-day row (matches on_conflict_do_update).
credit_shadow_picks keeps the EARLIEST same-day row (matches on_conflict_do_nothing).

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

# (table, constraint, decided_at order for the same-day row that survives)
TABLES = (
    ("shadow_picks", "uq_shadow_picks_symbol_event_eval", "DESC"),
    ("credit_shadow_picks", "uq_credit_shadow_picks_symbol_event_eval", "ASC"),
)


def upgrade() -> None:
    conn = op.get_bind()
    for table, constraint, keep_order in TABLES:
        op.add_column(table, sa.Column("eval_date", sa.Date, nullable=True))
        conn.execute(sa.text(f"""
            UPDATE {table}
            SET eval_date = (decided_at AT TIME ZONE 'America/New_York')::date
        """))
        op.alter_column(table, "eval_date", nullable=False)

        before = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        result = conn.execute(sa.text(f"""
            DELETE FROM {table}
            WHERE id NOT IN (
                SELECT DISTINCT ON (symbol, event_date, eval_date) id
                FROM {table}
                ORDER BY symbol, event_date, eval_date, decided_at {keep_order}, id
            )
        """))
        print(
            f"  l8m9n0o1p2q3: {table} same-day repeats deleted: "
            f"{result.rowcount} of {before} rows"
        )

        op.create_unique_constraint(constraint, table, ["symbol", "event_date", "eval_date"])


def downgrade() -> None:
    for table, constraint, _ in TABLES:
        op.drop_constraint(constraint, table)
        op.drop_column(table, "eval_date")
