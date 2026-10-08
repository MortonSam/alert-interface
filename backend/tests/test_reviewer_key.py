"""A reviewer key reads the ledger exactly as the admin token does, and nothing else.

REVIEWER_TOKENS (comma-separated) travel in X-Admin-Token like the admin token. While LEDGER_PUBLIC is
false, a request carrying one gets the same desk, Ivy trades and Ivy home reads as admin. It gets no
theses, no watchlists, no note regeneration, no admin endpoint, no write, and is never admin-local.
A route-table scan keeps the ledger gate on GET routes only, and a source scan keeps every
LEDGER_PUBLIC gate in the routers on the ledger gate rather than on is_admin.
"""
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import app.auth as auth
import app.routers.discover as discover
import app.routers.thesis as thesis
from app.auth import get_current_user, get_draft_caller, is_admin, may_read_ledger, require_admin, viewer_role
from app.main import app
from tests.route_scan import api_routes, dependency_calls

ADMIN_TOKEN, REVIEWER_A, REVIEWER_B = "test-admin-token", "reviewer-key-a", "reviewer-key-b"
ADMIN, REVIEWER, ANON = {"X-Admin-Token": ADMIN_TOKEN}, {"X-Admin-Token": REVIEWER_A}, {}
MISSING = str(uuid.uuid4())
LEDGER_READS = ["/api/v1/theses/ivy-activity", "/api/v1/theses/alert-picks", "/api/v1/discover/latest-pick"]


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", ADMIN_TOKEN)
    monkeypatch.setattr(auth.settings, "reviewer_tokens", f"{REVIEWER_A}, {REVIEWER_B},")   # blanks are not keys
    monkeypatch.setattr(thesis, "LEDGER_PUBLIC", False)
    monkeypatch.setattr(discover, "LEDGER_PUBLIC", False)


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_a_reviewer_key_passes_the_ledger_gate_exactly_as_the_admin_token_does(configured):
    async with _client() as c:
        for path in LEDGER_READS:
            as_admin = await c.get(path, headers=ADMIN)
            as_reviewer = await c.get(path, headers=REVIEWER)
            as_anon = await c.get(path)
            assert as_admin.status_code == as_reviewer.status_code == as_anon.status_code == 200, path
            assert as_reviewer.json() == as_admin.json(), path
        # anonymous gets the gated shape (what the database holds does not matter here)
        assert (await c.get("/api/v1/theses/alert-picks")).json() == []
        assert (await c.get("/api/v1/discover/latest-pick")).json() == {"pick": None}
        anon_activity = (await c.get("/api/v1/theses/ivy-activity")).json()
        assert anon_activity["ledger_public"] is False and anon_activity["rows"] == [] and anon_activity["run_date"] is None


@pytest.mark.asyncio
async def test_a_reviewer_key_gets_nothing_else(configured):
    async with _client() as c:
        for path in ["/api/v1/theses", "/api/v1/watchlists", f"/api/v1/theses/{MISSING}", f"/api/v1/watchlists/{MISSING}",
                     "/api/v1/admin/chain-expirations", "/api/v1/admin/shadow-summary"]:
            r = await c.get(path, headers=REVIEWER)
            assert r.status_code == 401, (path, r.status_code, r.text)
            assert "admin-local" not in r.text
        for coro in [
            c.post("/api/v1/theses", json={"symbol": "AAPL", "direction": "bullish", "conviction": 3, "target_date": "2026-12-31"}, headers=REVIEWER),
            c.delete(f"/api/v1/theses/{MISSING}", headers=REVIEWER),
            c.post("/api/v1/watchlists", json={"name": "x", "description": None}, headers=REVIEWER),
            c.post("/api/v1/research-notes/verify", json={"symbol": "AAPL"}, headers=REVIEWER),
            c.post("/api/v1/admin/ingest-options-chains", headers=REVIEWER),
        ]:
            r = await coro
            assert r.status_code == 401, (r.request.method, r.request.url.path, r.status_code, r.text)
        # note generation: a reviewer is a visitor
        policy_reviewer = (await c.get("/api/v1/research-notes/policy", headers=REVIEWER)).json()
        policy_anon = (await c.get("/api/v1/research-notes/policy")).json()
        assert policy_reviewer == policy_anon


@pytest.mark.asyncio
async def test_a_reviewer_key_is_never_admin_local_and_blanks_are_not_keys(configured):
    for key in (REVIEWER_A, REVIEWER_B):
        assert viewer_role(key) == "reviewer" and may_read_ledger("reviewer") is True
        assert is_admin(key) is False
        with pytest.raises(HTTPException) as e:
            await require_admin(key)
        assert e.value.status_code == 401
        with pytest.raises(HTTPException) as e:
            await get_current_user(None, key, None)
        assert e.value.status_code == 401
        assert await get_draft_caller(None, None, key, None) == "anon"
    assert viewer_role(ADMIN_TOKEN) == "admin" and is_admin(ADMIN_TOKEN) is True
    for not_a_key in (None, "", " ", "wrong", "reviewer-key-c"):
        assert viewer_role(not_a_key) == "anon" and may_read_ledger(viewer_role(not_a_key)) is False


@pytest.mark.asyncio
async def test_with_no_reviewer_tokens_configured_no_key_is_a_reviewer(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", ADMIN_TOKEN)
    monkeypatch.setattr(auth.settings, "reviewer_tokens", "")
    assert auth.reviewer_tokens() == frozenset()
    assert viewer_role(REVIEWER_A) == "anon" and viewer_role("") == "anon" and viewer_role(ADMIN_TOKEN) == "admin"
    monkeypatch.setattr(auth.settings, "reviewer_tokens", " , ,")
    assert auth.reviewer_tokens() == frozenset() and viewer_role(" ") == "anon"


def test_the_ledger_gate_is_on_the_three_ledger_reads_and_on_nothing_that_writes():
    routes = api_routes(app)
    assert len(routes) > 50, "the route walk found the app's routes"
    gated = {path: set(route.methods) for path, route in routes if may_read_ledger in dependency_calls(route.dependant)}
    assert gated == {path: {"GET"} for path in LEDGER_READS}


def test_every_ledger_public_gate_in_the_routers_is_the_ledger_gate_not_is_admin():
    routers = Path(__file__).resolve().parents[1] / "app" / "routers"
    for p in routers.glob("*.py"):
        src = p.read_text()
        for m in re.finditer(r"if not LEDGER_PUBLIC and not (\w+)", src):
            assert m.group(1) == "ledger_reader", (p.name, m.group(0))
        if "LEDGER_PUBLIC" in src and "if not LEDGER_PUBLIC" in src:
            assert "may_read_ledger" in src and "Depends(is_admin)" not in src, p.name

# shares rows other files of this group read across tickers (alert picks, seeded ZZ symbols, index membership): one xdist worker runs them
# (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="shared_rows")
