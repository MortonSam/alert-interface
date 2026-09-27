"""Auth: admin-token gating + Clerk JWT verification + per-user ownership.

No request is attributed to admin-local unless it carries the admin token.
With no ADMIN_TOKEN configured nothing is admin: writes and reads of personal
data return 401, the ledger stays behind LEDGER_PUBLIC and drafts are rate
limited as anonymous. Local development sets ADMIN_TOKEN in backend/.env and
stores the same value as ``admin_token`` in the browser's localStorage.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, Header, HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

# ── Admin-token auth (unchanged) ──────────────────────────────────────────────

def _get_admin_token(x_admin_token: str | None = Header(None)) -> str | None:
    return x_admin_token


def _admin_token_matches(token: str | None) -> bool:
    """True only when ADMIN_TOKEN is configured and the request carries it."""
    return bool(settings.admin_token) and token == settings.admin_token


async def require_admin(token: str | None = Depends(_get_admin_token)) -> None:
    """Raise 401 unless the request carries the configured admin token."""
    if not _admin_token_matches(token):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


def is_admin(token: str | None = Depends(_get_admin_token)) -> bool:
    """Return True if the request carries the configured admin token. Never raises."""
    return _admin_token_matches(token)


# ── Clerk JWKS (lazy singleton) ───────────────────────────────────────────────

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient | None:
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    if not settings.clerk_jwks_url:
        return None
    _jwks_client = PyJWKClient(settings.clerk_jwks_url)
    return _jwks_client


def verify_clerk_jwt(token: str) -> dict:
    """Decode RS256 JWT via JWKS. Returns decoded payload with 'sub' claim.

    Raises HTTPException(401) on any verification failure.
    """
    client = _get_jwks_client()
    if client is None:
        raise HTTPException(status_code=401, detail="Clerk auth not configured")
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    # Validate authorized party (azp) if configured
    if settings.clerk_authorized_party:
        azp = payload.get("azp", "")
        if azp != settings.clerk_authorized_party:
            raise HTTPException(status_code=401, detail="Invalid authorized party")

    return payload


# ── User resolution ───────────────────────────────────────────────────────────

SIGN_IN_REQUIRED = (
    "Sign in required. Saved trades and watchlists belong to the account that made them; "
    "saving is in private beta."
)

def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def get_current_user(
    authorization: str | None = Header(None),
    x_admin_token: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Resolve caller identity. Returns user_id string.

    Priority:
    1. Bearer JWT (if JWKS configured) → Clerk user_id, upserts into users table
    2. Admin token match → "admin-local"
    3. Neither → 401 (there is no default identity)
    """
    # 1. Try Bearer JWT
    bearer = _extract_bearer(authorization)
    if bearer and _get_jwks_client() is not None:
        payload = verify_clerk_jwt(bearer)
        user_id = payload["sub"]
        email = payload.get("email") or payload.get("email_address")
        # Upsert user
        stmt = pg_insert(User).values(id=user_id, email=email)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"email": email})
        await db.execute(stmt)
        await db.flush()
        return user_id

    # 2. Admin token
    if _admin_token_matches(x_admin_token):
        return "admin-local"

    # 3. No valid credentials
    raise HTTPException(status_code=401, detail=SIGN_IN_REQUIRED)


async def get_draft_caller(
    request: Request,
    authorization: str | None = Header(None),
    x_admin_token: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Resolve caller identity for draft endpoints. Returns user_id or "anon".

    Same priority as get_current_user but never raises 401:
    1. Bearer JWT → Clerk user_id
    2. Admin token match → "admin-local"
    3. Otherwise → "anon" (rate limited by draft_limiter)
    """
    bearer = _extract_bearer(authorization)
    if bearer and _get_jwks_client() is not None:
        payload = verify_clerk_jwt(bearer)
        user_id = payload["sub"]
        email = payload.get("email") or payload.get("email_address")
        stmt = pg_insert(User).values(id=user_id, email=email)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"email": email})
        await db.execute(stmt)
        await db.flush()
        return user_id

    if _admin_token_matches(x_admin_token):
        return "admin-local"

    return "anon"


def check_ownership(resource_user_id: str, caller_user_id: str) -> None:
    """Raise 403 unless the caller owns the resource or is admin-local."""
    if caller_user_id == "admin-local":
        return
    if resource_user_id != caller_user_id:
        raise HTTPException(status_code=403, detail="Not your resource")
