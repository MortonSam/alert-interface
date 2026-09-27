"""No request is attributed to admin-local without the admin token.

Personal reads (theses, watchlists, a thesis by id and its marks) and every
write return 401 without credentials; the admin token still works; with no
ADMIN_TOKEN configured nothing is admin. A route-table scan keeps every write
in the app behind get_current_user or require_admin, except the three draft
endpoints, which are open to anonymous callers on purpose (rate limited).
"""
import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import app.auth as auth
from app.auth import get_current_user, get_draft_caller, is_admin, require_admin
from app.main import app

TOKEN = "test-admin-token"
ADMIN = {"X-Admin-Token": TOKEN}
MISSING = str(uuid.uuid4())
BODY = {"symbol": "AAPL", "direction": "bullish", "conviction": 3, "target_date": "2026-12-31"}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", TOKEN)


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", "")


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


PERSONAL_READS = ["/api/v1/theses", "/api/v1/watchlists", f"/api/v1/theses/{MISSING}",
                  f"/api/v1/theses/{MISSING}/mark", f"/api/v1/theses/{MISSING}/stock-mark",
                  f"/api/v1/watchlists/{MISSING}"]


@pytest.mark.asyncio
async def test_personal_reads_are_401_without_credentials(configured):
    async with _client() as c:
        for path in PERSONAL_READS:
            r = await c.get(path)
            assert r.status_code == 401, (path, r.status_code, r.text)
            assert "admin-local" not in r.text
            r = await c.get(path, headers={"X-Admin-Token": "wrong"})
            assert r.status_code == 401, (path, "wrong token", r.status_code)


@pytest.mark.asyncio
async def test_writes_are_401_without_credentials(configured):
    async with _client() as c:
        checks = [
            c.post("/api/v1/theses", json=BODY),
            c.delete(f"/api/v1/theses/{MISSING}"),
            c.post(f"/api/v1/theses/{MISSING}/resolve", json={"reflection": "", "self_grade": "right"}),
            c.post("/api/v1/watchlists", json={"name": "x", "description": None}),
            c.delete(f"/api/v1/watchlists/{MISSING}"),
        ]
        for coro in checks:
            r = await coro
            assert r.status_code == 401, (r.request.method, r.request.url.path, r.status_code, r.text)


@pytest.mark.asyncio
async def test_admin_token_still_works(configured):
    async with _client() as c:
        r = await c.get("/api/v1/theses", headers=ADMIN)
        assert r.status_code == 200 and isinstance(r.json(), list)
        r = await c.get("/api/v1/watchlists", headers=ADMIN)
        assert r.status_code == 200
        # auth passed: the missing row is what fails, not the credential
        assert (await c.delete(f"/api/v1/theses/{MISSING}", headers=ADMIN)).status_code == 404
        assert (await c.get(f"/api/v1/theses/{MISSING}", headers=ADMIN)).status_code == 404


@pytest.mark.asyncio
async def test_no_configured_token_means_nobody_is_admin(unconfigured):
    with pytest.raises(HTTPException) as e:
        await get_current_user(None, None, None)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException):
        await get_current_user(None, "", None)
    assert await get_draft_caller(None, None, None, None) == "anon"
    assert is_admin(None) is False and is_admin("") is False
    with pytest.raises(HTTPException):
        await require_admin(None)
    async with _client() as c:
        assert (await c.get("/api/v1/theses")).status_code == 401
        assert (await c.post("/api/v1/theses", json=BODY)).status_code == 401


@pytest.mark.asyncio
async def test_only_the_configured_token_is_admin_local(configured):
    assert await get_current_user(None, TOKEN, None) == "admin-local"
    assert await get_draft_caller(None, None, TOKEN, None) == "admin-local"
    assert await get_draft_caller(None, None, "wrong", None) == "anon"
    with pytest.raises(HTTPException):
        await get_current_user(None, "wrong", None)


OPEN_DRAFT_ROUTES = {"/api/v1/theses/draft", "/api/v1/theses/alert-pick", "/api/v1/theses/draft-alternative"}


def _dependency_calls(dependant) -> set:
    calls = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            calls.add(d.call)
        stack.extend(d.dependencies)
    return calls


def test_every_write_route_requires_credentials():
    from fastapi.routing import APIRoute
    unguarded = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not (route.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        calls = _dependency_calls(route.dependant)
        if route.path in OPEN_DRAFT_ROUTES:
            assert get_draft_caller in calls, route.path
            continue
        if get_current_user not in calls and require_admin not in calls:
            unguarded.append(f"{sorted(route.methods)} {route.path}")
    assert unguarded == [], unguarded


def test_no_router_falls_back_to_admin_local():
    from pathlib import Path
    routers = Path(__file__).resolve().parents[1] / "app" / "routers"
    offenders = [p.name for p in routers.glob("*.py") if '"admin-local"' in p.read_text() or "get_optional_user" in p.read_text()]
    assert offenders == [], offenders
