"""iv_history by source (courier rows as before, solver rows beside them) and a rates table for the solver's rate.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("iv_history", sa.Column("iv_source", sa.String(20), nullable=False, server_default="courier"))
    op.add_column("iv_history", sa.Column("iv_version", sa.SmallInteger(), nullable=True))        # null: the vendor's IV as stored by snapshot_iv
    op.add_column("iv_history", sa.Column("expiration", sa.Date(), nullable=True))
    op.add_column("iv_history", sa.Column("atm_call_mid", sa.Numeric(12, 4), nullable=True))
    op.add_column("iv_history", sa.Column("atm_put_mid", sa.Numeric(12, 4), nullable=True))
    op.add_column("iv_history", sa.Column("solved_call_iv", sa.Numeric(8, 6), nullable=True))
    op.add_column("iv_history", sa.Column("solved_put_iv", sa.Numeric(8, 6), nullable=True))
    op.add_column("iv_history", sa.Column("vendor_call_iv", sa.Numeric(8, 6), nullable=True))
    op.add_column("iv_history", sa.Column("vendor_put_iv", sa.Numeric(8, 6), nullable=True))
    op.add_column("iv_history", sa.Column("vendor_iv", sa.Numeric(8, 6), nullable=True))
    op.add_column("iv_history", sa.Column("rate", sa.Numeric(8, 6), nullable=True))                 # annual, decimal
    op.add_column("iv_history", sa.Column("rate_date", sa.Date(), nullable=True))
    op.add_column("iv_history", sa.Column("days_to_expiry", sa.SmallInteger(), nullable=True))
    op.drop_constraint("uq_iv_history_symbol_date", "iv_history", type_="unique")
    op.create_unique_constraint("uq_iv_history_symbol_date_source", "iv_history", ["symbol", "date", "iv_source"])
    op.create_table(
        "rates",
        sa.Column("series", sa.String(20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(10, 6), nullable=False),          # as published, percent
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("series", "date", name="pk_rates"),
    )


def downgrade() -> None:
    op.drop_table("rates")
    op.drop_constraint("uq_iv_history_symbol_date_source", "iv_history", type_="unique")
    op.create_unique_constraint("uq_iv_history_symbol_date", "iv_history", ["symbol", "date"])
    for col in ("days_to_expiry", "rate_date", "rate", "vendor_iv", "vendor_put_iv", "vendor_call_iv", "solved_put_iv", "solved_call_iv",
                "atm_put_mid", "atm_call_mid", "expiration", "iv_version", "iv_source"):
        op.drop_column("iv_history", col)
