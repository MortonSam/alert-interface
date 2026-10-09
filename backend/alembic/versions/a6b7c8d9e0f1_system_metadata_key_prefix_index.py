"""system_metadata gets a prefix index on key (text_pattern_ops): chain lookups by prefix ("intrinio_chain:MU:%") scanned all
~10,400 rows (7 ms each), several times per ticker read once the options source resolver ran on every chain read.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
"""
from alembic import op

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_system_metadata_key_prefix ON system_metadata (key text_pattern_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_system_metadata_key_prefix")
