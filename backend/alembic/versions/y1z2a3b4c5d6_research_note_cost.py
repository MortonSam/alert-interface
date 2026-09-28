"""research_notes: verification token counts and the estimated cost of the note.

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "y1z2a3b4c5d6"
down_revision = "x0y1z2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_notes", sa.Column("verification_input_tokens", sa.Integer(), nullable=True))
    op.add_column("research_notes", sa.Column("verification_output_tokens", sa.Integer(), nullable=True))
    op.add_column("research_notes", sa.Column("estimated_cost_usd", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("research_notes", "estimated_cost_usd")
    op.drop_column("research_notes", "verification_output_tokens")
    op.drop_column("research_notes", "verification_input_tokens")
