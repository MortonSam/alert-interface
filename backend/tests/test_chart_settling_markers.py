"""A confirmed report shows its earnings marker on the price chart as soon as its date passes, while its reaction window is still
settling (JPM's Oct 13, 2026 report had none); the reaction row fills in the outcome and the moves when it lands (Sam, 2026-10-19)."""
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.chart_markers import settling_dates, today_ny

pytestmark = pytest.mark.xdist_group(name="shared_rows")
SYM = "ZZMRK"


def test_settling_dates_are_confirmed_past_reports_without_a_reaction():
    d = date(2026, 10, 13)
    assert settling_dates([], [d], date(2025, 10, 19), date(2026, 10, 19)) == [d]                    # JPM, Oct 13: a marker now
    assert settling_dates([d], [d], date(2025, 10, 19), date(2026, 10, 19)) == []                     # its reaction row landed
    assert settling_dates([d + timedelta(days=1)], [d], date(2025, 10, 19), date(2026, 10, 19)) == []  # an after-close row a day on
    assert settling_dates([], [date(2026, 10, 20)], date(2025, 10, 19), date(2026, 10, 19)) == []     # not yet reported
    assert settling_dates([], [date(2025, 7, 1)], date(2025, 10, 19), date(2026, 10, 19)) == []       # before the chart's window


@pytest.mark.asyncio
async def test_the_chart_marks_a_settling_report_and_never_an_estimated_one():
    from app.main import app
    today = today_ny()
    settled, settling, estimated, future = today - timedelta(days=90), today - timedelta(days=2), today - timedelta(days=30), today + timedelta(days=20)
    async with ScriptSessionLocal() as s:
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Marker test', false) ON CONFLICT (symbol) DO NOTHING"), {"s": SYM})
        tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": SYM})).scalar()
        await s.execute(text("DELETE FROM events WHERE ticker_id = :t"), {"t": tid})
        await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id = :t"), {"t": tid})
        for d, confirmed in ((settled, True), (settling, True), (estimated, False), (future, True)):
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, report_timing)
                VALUES (gen_random_uuid(), :t, 'earnings', :d, 'ZZMRK earnings', 'manual', :c, '{}', 'bmo')"""), {"t": tid, "d": d, "c": confirmed})
        await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, eps_estimate, eps_actual, outcome, computation_version)
            VALUES (gen_random_uuid(), :t, 'earnings', :d, 2.5, 1.00, 1.10, 'beat', 3)"""), {"t": tid, "d": settled})
        await s.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/v1/tickers/chart/{SYM}?period=1y")
        assert r.status_code == 200, r.text
        marks = {m["date"]: m for m in r.json()["earnings_markers"]}
        assert set(marks) == {settled.isoformat(), settling.isoformat()}
        assert marks[settled.isoformat()]["outcome"] == "beat" and marks[settled.isoformat()]["pct_change_1d"] == 2.5
        s2 = marks[settling.isoformat()]
        assert s2["outcome"] == "unknown" and s2["pct_change_1d"] is None and s2["eps_actual"] is None and s2["report_timing"] == "bmo"
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
            await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
            await s.commit()
