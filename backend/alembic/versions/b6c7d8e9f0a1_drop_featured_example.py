"""The home page's featured example is gone: its stored pick, its step stamp and its step outcome go with it.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
"""
from alembic import op

revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM system_metadata WHERE key IN ('featured_example', 'step:Featured example:last_success')")
    op.execute("UPDATE system_metadata SET value = (value::jsonb - 'Featured example')::text WHERE key = 'step_outcomes' AND value::jsonb ? 'Featured example'")


def downgrade() -> None:
    pass        # a deleted pick is not restored; the nightly that chose it no longer exists
