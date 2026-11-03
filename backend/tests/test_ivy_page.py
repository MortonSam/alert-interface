"""The /ivy page's live parts (routers/walkthrough /ivy-page, Sam 2026-11-02): hidden with the walkthrough flag, and its quick picks
are the three Sam named."""
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
    assert R.IVY_QUICK_PICKS == ("NVDA", "AAPL", "JPM")
