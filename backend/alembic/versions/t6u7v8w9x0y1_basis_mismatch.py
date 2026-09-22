"""basis_mismatch on eps_basis_checks; basis_excluded on earnings_features.

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "t6u7v8w9x0y1"
down_revision = "s5t6u7v8w9x0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eps_basis_checks", sa.Column("estimate_status", sa.String(16)))
    op.add_column("eps_basis_checks",
                  sa.Column("basis_mismatch", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_index("ix_eps_basis_checks_mismatch", "eps_basis_checks", ["basis_mismatch"])
    op.add_column("earnings_features",
                  sa.Column("basis_excluded", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("earnings_features", "basis_excluded")
    op.drop_index("ix_eps_basis_checks_mismatch", table_name="eps_basis_checks")
    op.drop_column("eps_basis_checks", "basis_mismatch")
    op.drop_column("eps_basis_checks", "estimate_status")
