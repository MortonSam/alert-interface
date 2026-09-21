"""NULL put/call ratios where either side has < 50 contracts.

Replaces the old total-contracts guard with a per-side guard.
Rows where put_total < 50 or call_total < 50 should not have a ratio.

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "j6k7l8m9n0o1"
down_revision = "i5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("""
            UPDATE put_call_snapshots
            SET ratio = NULL
            WHERE ratio IS NOT NULL
              AND (put_total < 50 OR call_total < 50)
        """)
    )


def downgrade() -> None:
    # Data migration — cannot restore original ratios.
    pass
