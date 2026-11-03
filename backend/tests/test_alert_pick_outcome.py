"""Ivy's pick outcomes keep their labels, and "Let Ivy decide" is gone (Sam, 2026-11-02): no route lets Ivy choose a
visitor's direction, and a draft takes only bullish or bearish. No draft failure detail carries exception text.
"""
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.routers.thesis as thesis
from app.main import app
from app.services.ivy_outcomes import IVY_OUTCOMES, ivy_outcome_label

@pytest.mark.asyncio
async def test_there_is_no_let_ivy_decide_and_a_draft_takes_only_the_visitors_direction():
    """Sam, 2026-11-02: the visitor always chooses the direction; Ivy never picks bullish or bearish for them."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/v1/theses/alert-pick", json={"symbol": "AAPL"})).status_code in (404, 405)
        for direction in ("auto", "neutral", "mixed_evidence", ""):
            r = await c.post("/api/v1/theses/draft", json={"symbol": "AAPL", "direction": direction, "aggressiveness": "moderate"})
            assert r.status_code == 422, (direction, r.text)
    assert thesis.DRAFT_DIRECTIONS == ("bullish", "bearish")


def test_every_outcome_the_route_can_emit_has_a_label_and_no_failure_detail_carries_the_exception():
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
    emitted = set(re.findall(r'"outcome":\s*"([a-z_]+)"', src)) | set(re.findall(r'outcome_code = "([a-z_]+)"', src))
    assert emitted and emitted <= set(IVY_OUTCOMES), emitted - set(IVY_OUTCOMES)
    assert ivy_outcome_label("skipped").startswith("Passed") and ivy_outcome_label("nonsense") == IVY_OUTCOMES["error"]["label"]
    assert not re.search(r'detail=f"[^"]*\{exc\}', src), "a visitor would read exception text"
    assert "detail=MARKET_DATA_UNAVAILABLE" in src and "detail=DRAFT_UNAVAILABLE" in src
    for sentence in (thesis.MARKET_DATA_UNAVAILABLE, thesis.DRAFT_UNAVAILABLE):
        assert sentence.endswith(".") and "{" not in sentence and "Error" not in sentence
