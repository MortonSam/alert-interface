"""The /ivy page's live parts (routers/walkthrough /ivy-page, Sam 2026-11-02): hidden with the walkthrough flag, and its quick picks
chosen by rule: walkthroughs with content on all seven steps (Sam, 2026-11-10)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.routers import walkthrough as R


@pytest.mark.asyncio
async def test_the_ivy_page_answers_only_with_the_walkthrough_flag(monkeypatch):
    monkeypatch.setattr(settings, "ivy_walkthrough_enabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/ivy-page")).status_code == 404
    assert R.QUICK_PICK_COUNT == 2 and not hasattr(R, "IVY_QUICK_PICKS")


def test_a_quick_pick_has_content_on_every_step():
    step = lambda n, status="ok", **k: {"n": n, "status": status, "numbers": [{"x": 1}], "sentences": [], **k}
    assert R.full({"entry": True, "steps": [step(n) for n in range(1, 8)]})
    assert not R.full({"entry": True, "steps": [step(n) for n in range(1, 7)] + [step(7, "absent")]})
    assert not R.full({"entry": True, "steps": [step(n) for n in range(1, 7)] + [{"n": 7, "status": "partial", "numbers": [], "sentences": []}]})
    assert not R.full({"entry": False, "steps": [step(n) for n in range(1, 8)]}) and not R.full(None)
