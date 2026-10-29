"""Accounts (Sam, 2026-10-29, behind ACCOUNTS_ENABLED): email magic-link sign-in, sessions, email preferences and the one-email-a-day
log; a saved trade records what options priced when it was saved and its scored result after expiration.

users gains email_lower (unique, the sign-in identity) and last_sign_in_at; ids for email accounts are "acct_<uuid>".
auth_links holds a sign-in link's token hashed (sha256), its expiry (15 minutes) and its one use; auth_sessions a session cookie's
token hashed, revocable one by one or all at once. email_prefs is one row per person and email kind (all off until turned on).
email_sends holds at most one row per person and New York day (the one email, its kinds merged).

Revision ID: a1c2c0d9e7f5
Revises: b4d6e8f0a2c4 (main's head since 07dfbce; was f3c4d5e6f7a8 before the rebase of 2026-11-02)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1c2c0d9e7f5"
down_revision = "b4d6e8f0a2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_lower", sa.String(320), nullable=True))
    op.add_column("users", sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("uq_users_email_lower", "users", ["email_lower"], unique=True)
    op.create_table(
        "auth_links",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("email_lower", sa.String(320), nullable=False, index=True),
        sa.Column("ip", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "email_prefs",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "email_sends",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("kinds", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("items", postgresql.JSONB, nullable=True),        # what it reported on ({kind, symbol, date}), so nothing is told twice
        sa.Column("provider_id", sa.String(128), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("theses", sa.Column("priced_move_pct", sa.Numeric(8, 4), nullable=True))        # options' implied move when saved
    op.add_column("theses", sa.Column("priced_move_as_of", sa.Date, nullable=True))
    op.add_column("theses", sa.Column("result", postgresql.JSONB, nullable=True))                 # services/trade_results, after expiration


def downgrade() -> None:
    op.drop_column("theses", "result")
    op.drop_column("theses", "priced_move_as_of")
    op.drop_column("theses", "priced_move_pct")
    op.drop_table("email_sends")
    op.drop_table("email_prefs")
    op.drop_table("auth_sessions")
    op.drop_table("auth_links")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_column("users", "last_sign_in_at")
    op.drop_column("users", "email_lower")
