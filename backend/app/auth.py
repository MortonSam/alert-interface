"""Auth: admin-token gating + Clerk JWT verification + per-user ownership."""

from __future__ import annotations

import jwt
from fastapi import Depends, Header, HTTPException
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


async def require_admin(token: str | None = Depends(_get_admin_token)) -> None:
    """Raise 401 if ADMIN_TOKEN is configured and the request doesn't match."""
    if not settings.admin_token:
        return  # no token configured → open access (dev mode)
    if token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


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
    3. Neither → 401
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
    if settings.admin_token and x_admin_token == settings.admin_token:
        return "admin-local"

    # 2b. No admin token configured → open access (dev mode)
    if not settings.admin_token:
        return "admin-local"

    # 3. No valid credentials
    raise HTTPException(status_code=401, detail="Authentication required")


async def get_optional_user(
    authorization: str | None = Header(None),
    x_admin_token: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str | None:
    """Same as get_current_user but returns None when no credentials provided.

    Used for public list endpoints where anon users see admin-local's data.
    """
    bearer = _extract_bearer(authorization)
    has_admin = x_admin_token is not None

    if not bearer and not has_admin:
        return None

    # Delegate to get_current_user for actual validation
    return await get_current_user(authorization, x_admin_token, db)


def check_ownership(resource_user_id: str, caller_user_id: str) -> None:
    """Raise 403 unless the caller owns the resource or is admin-local."""
    if caller_user_id == "admin-local":
        return
    if resource_user_id != caller_user_id:
        raise HTTPException(status_code=403, detail="Not your resource")
