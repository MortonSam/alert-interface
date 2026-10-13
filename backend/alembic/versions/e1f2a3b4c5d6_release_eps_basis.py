"""release_eps.eps_basis and basic_eps_gaap: a release that states no diluted EPS at all (ED 2026-08-06, "Reported earnings per share
(basic)") stores its basic figure as basic, never in diluted_eps_gaap. diluted_eps_gaap becomes nullable; a row holds exactly one of the
two figures, named by eps_basis. Every existing row is diluted (the default). Readers that use the figure as diluted EPS (compute_pe,
compute_growth, check_release_eps, valuation_report) read diluted rows only.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("release_eps", sa.Column("eps_basis", sa.String(8), nullable=False, server_default="diluted"))
    op.add_column("release_eps", sa.Column("basic_eps_gaap", sa.Numeric(12, 4), nullable=True))
    op.alter_column("release_eps", "diluted_eps_gaap", existing_type=sa.Numeric(12, 4), nullable=True)
    op.create_check_constraint(
        "release_eps_one_basis", "release_eps",
        "(eps_basis = 'diluted' AND diluted_eps_gaap IS NOT NULL AND basic_eps_gaap IS NULL) OR "
        "(eps_basis = 'basic' AND basic_eps_gaap IS NOT NULL AND diluted_eps_gaap IS NULL)")


def downgrade() -> None:
    op.execute("DELETE FROM release_eps WHERE eps_basis = 'basic'")
    op.drop_constraint("release_eps_one_basis", "release_eps", type_="check")
    op.alter_column("release_eps", "diluted_eps_gaap", existing_type=sa.Numeric(12, 4), nullable=False)
    op.drop_column("release_eps", "basic_eps_gaap")
    op.drop_column("release_eps", "eps_basis")
