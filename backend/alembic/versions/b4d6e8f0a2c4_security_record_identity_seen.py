"""security_records: the stored FIGI's share class, and the composite FIGI, share class FIGI and Intrinio security id Intrinio
returned at the last refresh, so validate's figi_change can tell a listing move (same security, a new exchange line: PANW's NYSE
FIGI to its Nasdaq one, 2026-10-29) from a different security.

Revision ID: b4d6e8f0a2c4
Revises: f3c4d5e6f7a8
"""
from alembic import op
import sqlalchemy as sa

revision = "b4d6e8f0a2c4"
down_revision = "f3c4d5e6f7a8"
branch_labels = None
depends_on = None

COLUMNS = ("share_class_figi", "seen_composite_figi", "seen_share_class_figi", "seen_security_id")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("security_records", sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("security_records", name)
