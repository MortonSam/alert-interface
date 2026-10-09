"""A pending cash deal (services/pending_deals) pauses earnings and options figures for its ticker, with one note naming the
deal price from the stored row, and keeps it out of picks and Discover's lists."""
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.scripts import set_pending_deal as W
from app.scripts.validate_data import deal_band_rows
from app.services import options_source
from app.services import pending_deals as D

pytestmark = pytest.mark.xdist_group(name="pending_deals")
SYM = "AES"


def test_the_note_is_sams_sentence_with_the_price_from_the_row():
    deal = D.Deal("AES", 15.0, "GIP and EQT", date(2026, 3, 2), "late 2026", "https://www.sec.gov/x")
    assert D.note_for(deal) == ("This company has agreed to be acquired for $15.00 a share in cash, so its price now tracks the deal "
                                "rather than its business. Earnings and options figures are paused.")
    assert "$1,250.50 a share" in D.note_for(D.Deal("X", 1250.5, "a", date(2026, 1, 1), None, "u"))


def test_validate_warns_outside_five_percent_either_way():
    deals = {"AES": D.Deal("AES", 15.0, "a", date(2026, 3, 2), None, "u"), "TECH": D.Deal("TECH", 73.0, "a", date(2026, 6, 25), None, "u"),
             "LOW": D.Deal("LOW", 10.0, "a", date(2026, 1, 1), None, "u"), "NONE": D.Deal("NONE", 5.0, "a", date(2026, 1, 1), None, "u")}
    rows = deal_band_rows(deals, {"AES": (14.93, "2026-10-08"), "TECH": (77.0, "2026-10-08"), "LOW": (9.4, "2026-10-08")}, D.PRICE_BAND_PCT)
    assert D.PRICE_BAND_PCT == 5.0
    assert [r.split()[0] for r in rows] == ["LOW", "NONE", "TECH"]
    assert "5.5% above the $73.00 deal price" in rows[2] and "6.0% below the $10.00 deal price" in rows[0]


def test_the_filing_check_reads_price_date_and_cik():
    assert W.cik_of_url("https://www.sec.gov/Archives/edgar/data/0000842023/000114036126033911/x.htm") == 842023
    import re
    for s in ("receive $15.00 per share in cash", "the $73.00 in cash per share of Bio-Techne", "$15.00 per share, in cash"):
        assert re.search(W.price_pattern(15.0 if "15" in s else 73.0), s, re.I), s
    assert not re.search(W.price_pattern(15.0), "a $15.00 per share dividend")
    body = "the President, effective March 2, 2026. " + "x " * 200 + "On March 2, 2026, the Company entered into an Agreement and Plan of Merger"
    assert "Agreement and Plan of Merger" in W.find_near(body, W.date_pattern(date(2026, 3, 2)), W.AGREEMENT_WORDS)
    assert W.find_near("effective March 2, 2026, a new President", W.date_pattern(date(2026, 3, 2)), W.AGREEMENT_WORDS) is None


@pytest_asyncio.fixture
async def held():
    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM pending_deals WHERE symbol = :s"), {"s": SYM})
        await s.execute(text("""INSERT INTO pending_deals (symbol, price_per_share, acquirer, agreed_on, filing_url, filing_evidence, filing_checked_at)
            VALUES (:s, 15.00, 'GIP and EQT', '2026-03-02', 'https://www.sec.gov/x', 'test', now())"""), {"s": SYM})
        await s.commit()
    options_source.clear_caches()
    yield D.note_for(D.Deal(SYM, 15.0, "", date(2026, 3, 2), None, ""))
    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM pending_deals WHERE symbol = :s"), {"s": SYM})
        await s.commit()
    options_source.clear_caches()


@pytest.mark.asyncio
async def test_a_held_ticker_shows_the_note_everywhere_and_gets_no_pick(held, monkeypatch):
    note = held
    from app.main import app
    from app.routers import thesis
    from app.services.fact_holds import holds_for, holds_for_symbols
    from app.services.iv_store import get_servable_iv
    async with AsyncSessionLocal() as db:
        assert (await options_source.resolve(db, SYM)).deal_note == note
        assert await options_source.no_options_note(db, SYM) == note
        assert (await get_servable_iv(db, SYM)).reason == note
        assert set(D.HELD_FACTS) <= set(await holds_for(db, SYM))
        assert set(D.HELD_FACTS) <= (await holds_for_symbols(db, [SYM, "MSFT"]))[SYM]
        r = await thesis.compute_alert_pick(SYM, db, source="manual", dry_run=True)
        assert r["outcome"] == "skipped" and r["note"] == note and r["pick_id"] is None
    async def slot(*a, **k):
        return {"c": 14.93, "t": 1791489600, "d": 0.0, "dp": 0.0, "pc": 14.93, "basis": "last_trade"}
    from app.services import finnhub_client
    monkeypatch.setattr(finnhub_client.FinnhubClient, "get_quote", slot)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        em = (await c.get(f"/api/v1/tickers/expected-move/{SYM}")).json()
        assert em["expected_move_pct"] is None and em["historical_stats"] is None and em["data_quality_note"] == note
        b = (await c.get(f"/api/v1/tickers/options-bundle/{SYM}")).json()
        assert b["expected_move"]["expected_move_pct"] is None and b["expected_move"]["data_quality_note"] == note and b["chain"]["calls"] == []
        rd = (await c.get(f"/api/v1/tickers/options-read/{SYM}")).json()
        assert rd["available"] is False and rd["reason"] == note
        assert (await c.get(f"/api/v1/tickers/put-call/{SYM}")).json()["reason"] == note
        summ = (await c.get(f"/api/v1/reactions/summary?symbol={SYM}")).json()
        assert summ["deal_note"] == note and summ["total_quarters"] == 0
        rows = (await c.get(f"/api/v1/reactions?symbol={SYM}")).json()
        assert not [r for r in rows if r["event_type"] == "earnings"]          # the earnings chart and distribution have nothing
        cond = (await c.get(f"/api/v1/reactions/conditional?symbol={SYM}")).json()
        assert cond["deal_note"] == note and cond["total_quarters"] == 0
        rv = (await c.get(f"/api/v1/tickers/rv/{SYM}")).json()
        assert rv["deal_note"] == note and rv["rv_rank"] is None and rv["rv_rank_labeled"] is None and rv["rv_percentile"] is None
        qs = (await c.get(f"/api/v1/tickers/{SYM}/questions")).json()
        assert "volatile_now" not in [q.get("key") for q in qs.get("questions", [])]
        sugg = (await c.get("/api/v1/discover/suggestions?limit=10")).json()
        assert SYM not in [i["symbol"] for i in sugg["items"]]
        ua = (await c.get("/api/v1/discover/unusually-active?limit=50")).json()
        assert SYM not in [i["symbol"] for i in ua["items"]]
        jr = (await c.get("/api/v1/discover/just-reported?days=30&limit=50")).json()
        assert SYM not in [i["symbol"] for i in jr["items"]]


@pytest.mark.asyncio
async def test_auto_pick_never_loads_a_held_ticker(held):
    from datetime import timedelta
    from app.scripts.auto_pick import _load_candidates
    async with AsyncSessionLocal() as s:
        rows = await _load_candidates(s, date.today() - timedelta(days=400), date.today() + timedelta(days=400))
    assert SYM not in [r.symbol for r in rows]


def test_a_leading_the_is_dropped_from_the_name_mid_sentence():
    from app.services.briefing import short_name
    assert short_name("The AES Corporation") == "AES"
    assert short_name("The Home Depot, Inc.") == "Home Depot"
    assert short_name("The Hershey Company") == "Hershey"
    assert short_name("Micron Technology, Inc.") == "Micron Technology"
    assert short_name("The") == "The"                      # nothing left to name: kept
