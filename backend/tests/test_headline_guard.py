"""The Discover headline guard (services/headline_guard): a headline beside a move must not contradict it, judged on the clauses
that name the stock."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import headline_guard as G
from app.services import news as N

INTC = N.name_forms("INTC", "Intel Corporation")
CMG = N.name_forms("CMG", "Chipotle Mexican Grill, Inc.")


def test_a_verb_pointing_the_other_way_is_suppressed():
    assert G.check("Intel shares surge on foundry deal", -3.1, INTC).reason == "its verb says up on a down day"
    assert G.check("Intel plunges after guidance cut", 4.0, INTC).reason == "its verb says down on an up day"
    assert G.check("Intel announces new chip", -1.0, INTC).reason is None


def test_only_the_clause_naming_the_stock_counts():
    assert G.check("Starbucks Slides 3% as Chipotle Mexican Grill Jumps 5% on Takeover Talk", 6.2, CMG).reason is None
    assert G.check("Chipotle jumps on report Starbucks explored a takeover", -0.4, N.name_forms("SBUX", "Starbucks Corporation")).reason is None
    assert G.check("Intel Q3 revenue jumps 20%", -2.0, INTC).reason is None                 # a non-price figure
    assert G.check("Why Intel Plunged in September", 2.5, INTC).reason is None              # a longer period
    assert G.check("Intel Stock Is Up 212% Since December", -5.3, INTC).reason is None


def test_the_number_check_suppresses_only_an_opposite_sign():
    assert G.check("Intel Slides 3% as Chip Stocks Sell Off", -5.3, INTC).reason is None     # same direction, a different size: passes
    assert G.check("Intel stock +5% premarket", -1.0, INTC).reason == "its stated move has the opposite sign"
    assert G.check("Intel stock falls 4%", None, INTC).reason is None


def test_both_word_lists_live_in_one_file():
    root = Path(__file__).parents[1] / "app"
    for p in root.rglob("*.py"):
        if p.name != "headline_guard.py":
            src = p.read_text()
            assert "UP_VERBS =" not in src and "DOWN_VERBS =" not in src, p


def test_only_a_headline_that_would_have_shown_is_counted():
    t, t2 = datetime(2026, 10, 8, 18, tzinfo=timezone.utc), datetime(2026, 10, 8, 17, tzinfo=timezone.utc)
    stories = [{"url": "u1", "headline": "Intel shares surge 9% on foundry deal", "source": "Reuters", "published_at": t, "related": ["INTC"]},
               {"url": "u2", "headline": "Intel stock jumps on chip news", "source": "Yahoo", "published_at": t2, "related": ["INTC"]},
               {"url": "u3", "headline": "Intel stock falls 3% on chip glut worries", "source": "Yahoo", "published_at": t2, "related": ["INTC"]}]
    suppressed: dict = {}
    h = N.top_headline(stories, "INTC", "Intel Corporation", None, None, -3.4, suppressed)
    assert h["url"] == "u3"
    assert list(suppressed) == [("INTC", "u1")]                    # u2 was suppressed too, but would never have shown
    assert suppressed[("INTC", "u1")]["stated_pct"] == 9.0 and suppressed[("INTC", "u1")]["move_pct"] == -3.4
    suppressed = {}
    ranked = N.in_the_news(stories, {"INTC": -3.4}, per_ticker=1, names={"INTC": "Intel Corporation"}, moves={"INTC": -3.4}, suppressed=suppressed)
    assert [r["url"] for r in ranked] == ["u3"]
    assert list(suppressed) == [("INTC", "u1")]
    assert N.guard_share(1, 5) == 0.2 and N.guard_share(2, 5) > N.GUARD_WARN_SHARE and N.guard_share(1, 0) is None


@pytest.mark.asyncio
async def test_validate_judges_only_while_the_news_flag_is_on(monkeypatch):
    from app.config import settings
    from app.scripts.validate_data import PASS, check_news_headline_guard
    monkeypatch.setattr(settings, "discover_news_enabled", False)
    r = await check_news_headline_guard(None)
    assert r.level == PASS and "off" in r.message
