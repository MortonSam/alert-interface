"""The expected-window level in Sam's words (2026-10-26), and no vendor estimate on any page while PERSONAL_USE_DATA_SHOWN is off.

A report date with no company confirmation reads "Next report expected around {Nov 4, 2026}, based on its past report dates (not yet
confirmed by the company)" on every surface that prints one (ticker header, Catalysts, Overview, Discover, Build a Trade; the frontend
renders lib/earningsSource.expectedWindowLine, the same template), and no response a page reads carries "estimated (Finnhub)" or
"estimated (Yahoo Finance)"."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.config import settings
from app.database import ScriptSessionLocal
from app.models.event import Event
from app.models.ticker import Ticker
from app.services import report_windows as W
from app.services.briefing import upcoming_clause
from app.services.next_earnings import EXPECTED_WINDOW, EXPECTED_WINDOW_LINE, expected_window_line, next_earnings_for

pytestmark = pytest.mark.xdist_group(name="shared_rows")
VENDOR_NOTES = ("estimated (Finnhub)", "estimated (Yahoo Finance)")


def test_the_wording_is_sams_verbatim():
    assert expected_window_line(date(2026, 11, 4)) == \
        "Next report expected around Nov 4, 2026, based on its past report dates (not yet confirmed by the company)"
    text_, inputs, dates = upcoming_clause(today=date(2026, 10, 26), next_date=date(2026, 11, 4), confirmation=EXPECTED_WINDOW)
    assert text_ == expected_window_line(date(2026, 11, 4)) + "." and dates == [] and "estimated" not in text_


async def _seed(sym: str, today: date):
    async with ScriptSessionLocal() as s:
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Window Test, Inc.', true)"), {"s": sym})
        t = (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one()
        s.add(Event(ticker_id=t.id, event_type="earnings", event_date=today + timedelta(days=9), title="Q3 earnings", source="finnhub",
                    is_confirmed=False, confirmation_note="estimated (Finnhub)"))
        s.add(Event(ticker_id=t.id, event_type="earnings", event_date=today + timedelta(days=100), title="Q4 earnings", source="yfinance",
                    is_confirmed=False, confirmation_note="estimated (Yahoo Finance)"))
        center = today + timedelta(days=10)
        rec = {"symbol": sym, "center": center.isoformat(), "start": (center - timedelta(days=2)).isoformat(), "end": (center + timedelta(days=3)).isoformat(),
               "pairs": 8, "source": W.SOURCE, "computation_version": W.WINDOW_VERSION, "computed_at": datetime.now(timezone.utc).isoformat()}
        await s.execute(text("INSERT INTO system_metadata (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
                        {"k": W.KEY.format(sym=sym), "v": json.dumps(rec)})
        await s.commit()
        return t.id, center


async def _cleanup(sym: str):
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
        await s.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": W.KEY.format(sym=sym)})
        await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
        await s.commit()


@pytest.mark.asyncio
async def test_no_page_shows_a_vendor_estimate_while_personal_use_data_is_held(monkeypatch):
    monkeypatch.setattr(settings, "personal_use_data_shown", False)
    monkeypatch.setattr(settings, "licensed_dates_only", False)
    sym, today = "ZZEW", date.today()
    await _cleanup(sym)
    try:
        tid, center = await _seed(sym, today)
        async with ScriptSessionLocal() as s:
            ne = await next_earnings_for(s, tid, today)
        assert ne.date is None and ne.confirmation == EXPECTED_WINDOW and ne.window_center == center and ne.note is None
        from app.main import app
        from app.routers.discover import _batch_next_earnings
        async with ScriptSessionLocal() as s:
            card = (await _batch_next_earnings(s, [sym]))[sym]
        assert card["earnings_confirmation"] == EXPECTED_WINDOW and card["earnings_window_center"] == center.isoformat() and card["earnings_date"] is None
        bodies = [json.dumps(card)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for path in (f"/api/v1/tickers/by-symbol/{sym}", f"/api/v1/tickers/{sym}/briefing", "/api/v1/events/upcoming?days=120", "/api/v1/tickers"):
                r = await c.get(path)
                assert r.status_code == 200, (path, r.status_code, r.text[:300])
                bodies.append(r.text)
            detail = (await c.get(f"/api/v1/tickers/by-symbol/{sym}")).json()
        assert detail["next_earnings_confirmation"] == EXPECTED_WINDOW and detail["next_earnings_window_center"] == center.isoformat()
        assert detail["next_earnings_date"] is None and detail["next_earnings_note"] is None
        for body in bodies:
            for note in VENDOR_NOTES:
                assert note not in body, note
    finally:
        await _cleanup(sym)
