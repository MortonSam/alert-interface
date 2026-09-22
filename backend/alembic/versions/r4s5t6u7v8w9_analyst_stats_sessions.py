"""Analyst reaction stats record distinct sessions next to action counts.

Statistics are taken over distinct event dates (several actions on one day
share one price move). The columns start at 0 and are filled by the next
compute_analyst_reactions run; until then a 0 next to a non-zero count means
"not yet recomputed" (validate check analyst_stats_sessions flags it).

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "r4s5t6u7v8w9"
down_revision = "q3r4s5t6u7v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyst_reaction_stats",
                  sa.Column("upgrade_sessions", sa.Integer, nullable=False, server_default="0"))
    op.add_column("analyst_reaction_stats",
                  sa.Column("downgrade_sessions", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("analyst_reaction_stats", "downgrade_sessions")
    op.drop_column("analyst_reaction_stats", "upgrade_sessions")
