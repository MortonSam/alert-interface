"""Add EPS, revenue, and outcome columns to historical_reactions

Revision ID: c4d5e6f7a8b3
Revises: b3c4d5e6f7a2
Create Date: 2026-05-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "c4d5e6f7a8b3"
down_revision: Union[str, None] = "b3c4d5e6f7a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE earnings_outcome_enum AS ENUM ('beat', 'miss', 'meet', 'unknown')
    """)

    op.add_column("historical_reactions",
        sa.Column("eps_estimate",      sa.Numeric(10, 4), nullable=True))
    op.add_column("historical_reactions",
        sa.Column("eps_actual",        sa.Numeric(10, 4), nullable=True))
    op.add_column("historical_reactions",
        sa.Column("revenue_estimate",  sa.BigInteger(),   nullable=True))
    op.add_column("historical_reactions",
        sa.Column("revenue_actual",    sa.BigInteger(),   nullable=True))
    op.add_column("historical_reactions",
        sa.Column(
            "outcome",
            postgresql.ENUM(name="earnings_outcome_enum", create_type=False),
            nullable=False,
            server_default="unknown",
        ))


def downgrade() -> None:
    op.drop_column("historical_reactions", "outcome")
    op.drop_column("historical_reactions", "revenue_actual")
    op.drop_column("historical_reactions", "revenue_estimate")
    op.drop_column("historical_reactions", "eps_actual")
    op.drop_column("historical_reactions", "eps_estimate")
    op.execute("DROP TYPE earnings_outcome_enum")
