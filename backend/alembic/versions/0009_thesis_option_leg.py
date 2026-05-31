"""Add option leg and P&L columns to theses

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("theses", sa.Column("option_type", sa.String(8)))          # "call" | "put"
    op.add_column("theses", sa.Column("strike", sa.Numeric(12, 4)))
    op.add_column("theses", sa.Column("option_expiration", sa.Date()))
    op.add_column("theses", sa.Column("entry_premium", sa.Numeric(12, 4)))   # mid at creation, server-captured
    op.add_column("theses", sa.Column("contracts", sa.SmallInteger(), server_default="1"))
    op.add_column("theses", sa.Column("strike2", sa.Numeric(12, 4)))         # second leg (spread)
    op.add_column("theses", sa.Column("entry_premium2", sa.Numeric(12, 4)))
    op.add_column("theses", sa.Column("spread_type", sa.String(32)))         # e.g. "bull_call_spread"
    op.add_column("theses", sa.Column("from_ai_draft", sa.Boolean(), server_default="false"))
    op.add_column("theses", sa.Column("option_pnl_dollars", sa.Numeric(12, 2)))  # filled at resolution
    op.add_column("theses", sa.Column("option_pnl_pct", sa.Numeric(8, 4)))


def downgrade() -> None:
    for col in [
        "option_pnl_pct", "option_pnl_dollars", "from_ai_draft",
        "spread_type", "entry_premium2", "strike2",
        "contracts", "entry_premium", "option_expiration",
        "strike", "option_type",
    ]:
        op.drop_column("theses", col)
