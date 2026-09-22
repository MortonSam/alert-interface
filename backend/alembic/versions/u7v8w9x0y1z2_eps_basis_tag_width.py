"""eps_basis_checks.xbrl_tag widens to 80: "derived_q4:IncomeLossFromContinuingOperationsPerDilutedShare" is 60 characters.

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "u7v8w9x0y1z2"
down_revision = "t6u7v8w9x0y1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("eps_basis_checks", "xbrl_tag", type_=sa.String(80), existing_type=sa.String(40))


def downgrade() -> None:
    op.alter_column("eps_basis_checks", "xbrl_tag", type_=sa.String(40), existing_type=sa.String(80))
