"""Email accounts (Sam, 2026-10-29), behind ACCOUNTS_ENABLED. Reading never needs one: an account only saves (watchlists, My Trades),
asks Ivy, and receives the emails a person turns on.

Sign-in is a magic link, never a password. A link's token is 32 random bytes, sent once by email and stored only as its sha256; it
works once and for LINK_MINUTES. Requests are limited per email (LINK_PER_EMAIL in LINK_WINDOW_MINUTES, LINK_PER_EMAIL_DAY a day)
and per IP (LINK_PER_IP_HOUR). A used link opens a session: another random token in an HttpOnly, Secure, SameSite=Lax cookie
(SESSION_COOKIE) for SESSION_DAYS, stored hashed, so a database read never yields a working cookie. "Sign out everywhere" revokes
every session of the person; "Delete my account" removes the person and everything they saved in one transaction.
A request for an unknown email answers exactly as for a known one (nothing tells a visitor whether an address has an account).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text, update

LINK_MINUTES = 15
LINK_PER_EMAIL = 3                  # sign-in links per email in LINK_WINDOW_MINUTES
LINK_WINDOW_MINUTES = 15
LINK_PER_EMAIL_DAY = 10
LINK_PER_IP_HOUR = 10
SESSION_DAYS = 30
SESSION_COOKIE = "ai_session"
ACCOUNT_PREFIX = "acct_"
EMAIL_MAX = 254
EMAIL_SHAPE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")

# every table holding what a person saved or set, cleared by delete_account (a test holds it to the models with a user_id)
PERSONAL_TABLES = ("auth_sessions", "email_prefs", "email_sends", "theses", "watchlists")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(raw: str | None) -> str | None:
    """Pure: the address as stored and compared (trimmed, lower case), or None when it is not an address."""
    e = (raw or "").strip().lower()
    return e if len(e) <= EMAIL_MAX and EMAIL_SHAPE.match(e) else None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class LinkVerdict:
    ok: bool
    why: str | None = None          # "unknown", "used", "expired"


def judge_link(link, now: datetime) -> LinkVerdict:
    """Pure: whether a stored link may sign its holder in now: it exists, has not been used and has not expired."""
    if link is None:
        return LinkVerdict(False, "unknown")
    if link.used_at is not None:
        return LinkVerdict(False, "used")
    if now >= link.expires_at:
        return LinkVerdict(False, "expired")
    return LinkVerdict(True)


def over_limits(per_email_window: int, per_email_day: int, per_ip_hour: int) -> str | None:
    """Pure: which request limit a new sign-in link would break, or None."""
    if per_email_window >= LINK_PER_EMAIL:
        return "email_window"
    if per_email_day >= LINK_PER_EMAIL_DAY:
        return "email_day"
    if per_ip_hour >= LINK_PER_IP_HOUR:
        return "ip_hour"
    return None


def cookie_settings(secure: bool = True) -> dict:
    """The session cookie's attributes (FastAPI Response.set_cookie keywords)."""
    return {"key": SESSION_COOKIE, "httponly": True, "secure": secure, "samesite": "lax", "max_age": SESSION_DAYS * 86400, "path": "/"}


LINK_RECORD_DAYS = 30            # a sign-in link's record (address, network address, times) is deleted 30 days after it was asked for
                                 # (privacy policy question 7, Sam 2026-11-03)


async def delete_old_links(db, now: datetime | None = None) -> int:
    """Delete sign-in link records older than LINK_RECORD_DAYS; uncommitted. Returns how many went."""
    res = await db.execute(text("DELETE FROM auth_links WHERE created_at < :c"), {"c": (now or now_utc()) - timedelta(days=LINK_RECORD_DAYS)})
    return res.rowcount or 0


async def request_link(db, email_raw: str, ip: str | None, now: datetime | None = None) -> tuple[str, str | None, str | None]:
    """(status, token, email): "sent" with a new token to email, "invalid" for a non-address, or "limited". The caller emails the
    token; the database keeps only its hash."""
    from app.models.account import AuthLink
    now = now or now_utc()
    email = normalize_email(email_raw)
    if not email:
        return "invalid", None, None
    counts = (await db.execute(text("""SELECT
            count(*) FILTER (WHERE email_lower = :e AND created_at > :w),
            count(*) FILTER (WHERE email_lower = :e AND created_at > :d),
            count(*) FILTER (WHERE ip = :ip AND created_at > :h)
        FROM auth_links WHERE (email_lower = :e OR ip = :ip) AND created_at > :d2"""),
        {"e": email, "ip": ip or "", "w": now - timedelta(minutes=LINK_WINDOW_MINUTES), "d": now - timedelta(days=1), "h": now - timedelta(hours=1),
         "d2": now - timedelta(days=1)})).one()
    if over_limits(counts[0], counts[1], counts[2] if ip else 0):
        return "limited", None, email
    token = new_token()
    db.add(AuthLink(token_hash=token_hash(token), email_lower=email, ip=ip, created_at=now, expires_at=now + timedelta(minutes=LINK_MINUTES)))
    await delete_old_links(db, now)
    await db.commit()
    return "sent", token, email


async def use_link(db, token: str, now: datetime | None = None) -> tuple[str | None, str | None, str | None]:
    """(session token, user id, why not): spends the link (once), finds or creates the person, opens a session."""
    from app.models.account import AuthLink, AuthSession
    from app.models.user import User
    now = now or now_utc()
    link = (await db.execute(select(AuthLink).where(AuthLink.token_hash == token_hash(token or "")).with_for_update())).scalar_one_or_none()
    v = judge_link(link, now)
    if not v.ok:
        return None, None, v.why
    link.used_at = now
    user = (await db.execute(select(User).where(User.email_lower == link.email_lower))).scalar_one_or_none()
    if user is None:
        user = User(id=f"{ACCOUNT_PREFIX}{uuid.uuid4().hex}", email=link.email_lower, email_lower=link.email_lower)
        db.add(user)
        await db.flush()
    user.last_sign_in_at = now
    session_token = new_token()
    db.add(AuthSession(token_hash=token_hash(session_token), user_id=user.id, created_at=now, last_seen_at=now, expires_at=now + timedelta(days=SESSION_DAYS)))
    await db.commit()
    return session_token, user.id, None


async def session_user(db, cookie: str | None, now: datetime | None = None) -> str | None:
    """The signed-in person's id for a session cookie, or None (no cookie, unknown, revoked or expired)."""
    from app.models.account import AuthSession
    if not cookie:
        return None
    now = now or now_utc()
    s = (await db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash(cookie)))).scalar_one_or_none()
    if s is None or s.revoked_at is not None or now >= s.expires_at:
        return None
    if (now - s.last_seen_at) > timedelta(hours=1):
        s.last_seen_at = now
        await db.commit()
    return s.user_id


async def sign_out(db, cookie: str | None, everywhere: bool = False, now: datetime | None = None) -> int:
    """Revoke this session, or every session of its person (everywhere). Returns how many were revoked."""
    from app.models.account import AuthSession
    now = now or now_utc()
    uid = await session_user(db, cookie, now)
    if uid is None:
        return 0
    q = update(AuthSession).where(AuthSession.revoked_at.is_(None))
    q = q.where(AuthSession.user_id == uid) if everywhere else q.where(AuthSession.token_hash == token_hash(cookie))
    n = (await db.execute(q.values(revoked_at=now))).rowcount
    await db.commit()
    return n


async def delete_account(db, user_id: str) -> dict:
    """Remove the person and everything they saved or set, in one transaction: {table: rows removed}."""
    from app.models.user import User
    if not user_id.startswith(ACCOUNT_PREFIX):
        raise ValueError("only an email account can be deleted here")
    out = {}
    email = (await db.execute(text("SELECT email_lower FROM users WHERE id = :u"), {"u": user_id})).scalar()
    out["auth_links"] = (await db.execute(text("DELETE FROM auth_links WHERE email_lower = :e"), {"e": email})).rowcount if email else 0
    from app.services.ai_spend import spend_day
    out["ask_count"] = (await db.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": f"ask_person:{user_id}:{spend_day()}"})).rowcount
    for table in PERSONAL_TABLES:
        out[table] = (await db.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})).rowcount
    out["users"] = (await db.execute(delete(User).where(User.id == user_id))).rowcount
    await db.commit()
    return out


# ── unsubscribe links: signed, no table ─────────────────────────────────────────────────────────────────────────────────────

def unsubscribe_sig(secret: str, user_id: str, kind: str) -> str:
    return hmac.new(secret.encode(), f"{user_id}:{kind}".encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_ok(secret: str, user_id: str, kind: str, sig: str) -> bool:
    return bool(secret) and hmac.compare_digest(unsubscribe_sig(secret, user_id, kind), sig or "")

