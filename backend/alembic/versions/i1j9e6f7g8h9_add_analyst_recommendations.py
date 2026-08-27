"""add analyst_recommendations table

Revision ID: i1j9e6f7g8h9
Revises: h0i8d5e6f7g8
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'i1j9e6f7g8h9'
down_revision: Union[str, None] = 'h0i8d5e6f7g8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analyst_recommendations",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id"), nullable=False, index=True),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("strong_buy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sell", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("strong_sell", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker_id", "period", name="uq_analyst_rec_ticker_period"),
    )


def downgrade() -> None:
    op.drop_table("analyst_recommendations")
