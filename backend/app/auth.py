"""Lightweight admin-token gating for AI-powered endpoints."""

from fastapi import Depends, Header, HTTPException

from app.config import settings


def _get_admin_token(x_admin_token: str | None = Header(None)) -> str | None:
    return x_admin_token


async def require_admin(token: str | None = Depends(_get_admin_token)) -> None:
    """Raise 403 if ADMIN_TOKEN is configured and the request doesn't match."""
    if not settings.admin_token:
        return  # no token configured → open access (dev mode)
    if token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid or missing admin token")
