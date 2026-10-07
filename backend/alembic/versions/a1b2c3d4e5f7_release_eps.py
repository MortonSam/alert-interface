"""release_eps: the GAAP diluted EPS a company stated in its earnings release (Item 2.02 8-K, EX-99.1) for a quarter XBRL
does not hold yet, with the filing as its receipt, and the XBRL figure once the 10-Q/10-K lands with any difference flagged.

Revision ID: a1b2c3d4e5f7
Revises: f0a1b2c3d4e5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_eps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),             # the earnings event the release belongs to
        sa.Column("period_end", sa.Date(), nullable=True),               # the quarter's end as the release states it
        sa.Column("diluted_eps_gaap", sa.Numeric(12, 4), nullable=False),
        sa.Column("how", sa.String(40), nullable=False),                 # highlights sentence | diluted EPS row | income statement EPS row
        sa.Column("evidence", sa.Text(), nullable=False),                # the sentence or row the figure was read from
        sa.Column("accession", sa.String(25), nullable=False),           # the 8-K
        sa.Column("exhibit", sa.String(120), nullable=False),            # the document within it
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("xbrl_eps", sa.Numeric(12, 4), nullable=True),         # the same quarter's XBRL figure once filed
        sa.Column("xbrl_form", sa.String(10), nullable=True),
        sa.Column("xbrl_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("difference", sa.Numeric(12, 4), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("symbol", "report_date", name="uq_release_eps_symbol_report"),
    )


def downgrade() -> None:
    op.drop_table("release_eps")
