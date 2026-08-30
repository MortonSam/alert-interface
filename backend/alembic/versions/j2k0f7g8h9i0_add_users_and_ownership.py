"""add users table and user_id ownership columns

Revision ID: j2k0f7g8h9i0
Revises: i1j9e6f7g8h9
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j2k0f7g8h9i0"
down_revision: Union[str, None] = "i1j9e6f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Add user_id columns (nullable first for backfill)
    op.add_column("watchlists", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("theses", sa.Column("user_id", sa.String(), nullable=True))

    # 3. Seed default user and backfill
    op.execute("INSERT INTO users (id) VALUES ('admin-local')")
    op.execute("UPDATE watchlists SET user_id = 'admin-local'")
    op.execute("UPDATE theses SET user_id = 'admin-local'")

    # 4. Set NOT NULL and add FK + indexes
    op.alter_column("watchlists", "user_id", nullable=False)
    op.alter_column("theses", "user_id", nullable=False)

    op.create_foreign_key("fk_watchlists_user_id", "watchlists", "users", ["user_id"], ["id"])
    op.create_foreign_key("fk_theses_user_id", "theses", "users", ["user_id"], ["id"])

    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])
    op.create_index("ix_theses_user_id", "theses", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_theses_user_id", table_name="theses")
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")

    op.drop_constraint("fk_theses_user_id", "theses", type_="foreignkey")
    op.drop_constraint("fk_watchlists_user_id", "watchlists", type_="foreignkey")

    op.drop_column("theses", "user_id")
    op.drop_column("watchlists", "user_id")

    op.drop_table("users")
