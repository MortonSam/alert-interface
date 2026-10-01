"""security_records: the Intrinio record each ticker resolves to on each date.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("intrinio_security_id", sa.Text(), nullable=True),     # null for a stored_history row
        sa.Column("figi", sa.Text(), nullable=True),
        sa.Column("composite_figi", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),                 # null while current
        sa.Column("role", sa.String(20), nullable=False),                # current | predecessor | stored_history
        sa.Column("source", sa.String(20), nullable=False),              # intrinio | stored
        sa.Column("figi_seen", sa.Text(), nullable=True),                # the FIGI Intrinio returned at the last refresh
        sa.Column("last_price_date", sa.Date(), nullable=True),          # Intrinio's last_stock_price at the last refresh
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol", "valid_from", name="uq_security_records_symbol_valid_from"),
    )
    op.create_index("ix_security_records_symbol", "security_records", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_security_records_symbol", table_name="security_records")
    op.drop_table("security_records")
