"""fact_holds: the facts validate has found wrong per ticker (services/fact_holds), replaced on every validate run; every surface that
uses a held fact for that ticker hides it until the check passes.

Revision ID: b8c9d2e4f5a6
Revises: a7b8c9d2e4f5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b8c9d2e4f5a6"
down_revision = "a7b8c9d2e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_holds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("fact", sa.String(24), nullable=False),            # services/fact_holds.FACTS
        sa.Column("check_name", sa.String(48), nullable=False),      # the validate check that failed
        sa.Column("detail", sa.Text(), nullable=True),               # the check's row
        sa.Column("since", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "fact", "check_name", name="uq_fact_holds_symbol_fact_check"),
    )
    op.create_index("ix_fact_holds_symbol", "fact_holds", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_fact_holds_symbol", table_name="fact_holds")
    op.drop_table("fact_holds")
