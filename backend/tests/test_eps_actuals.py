"""EPS actuals the night of the report: which rows match, what may be written, beat or miss, and the stale check."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import refresh
from app.scripts.seed_eps_actuals import finnhub_rows
from app.scripts.validate_data import PASS, WARN, check_eps_actuals_fresh, run_checks
from app.services.eps_actuals import LOOKBACK_SESSIONS, eps_outcome, fill_plan, is_stale, match_row, sessions_back

NOW = datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)


def test_a_vendor_row_matches_the_event_on_its_date_or_the_day_beside_it():
    rows = {date(2026, 9, 30): (3.03, 2.86), date(2026, 6, 25): (1.91, 1.60)}
    assert match_row(date(2026, 9, 30), rows) == (3.03, 2.86)
    assert match_row(date(2026, 10, 1), rows) == (3.03, 2.86)           # Yahoo dates an after-close report the next day
    assert match_row(date(2026, 10, 3), rows) is None
    fh = finnhub_rows([{"date": "2026-09-30", "symbol": "MU", "epsActual": 3.03, "epsEstimate": 2.86}, {"date": "2026-10-01", "symbol": "stz", "epsActual": None, "epsEstimate": 3.4},
                       {"date": "bad", "symbol": "X"}])
    assert fh == {"MU": {date(2026, 9, 30): (3.03, 2.86)}, "STZ": {date(2026, 10, 1): (None, 3.4)}}


def test_only_null_columns_are_written_and_never_an_existing_value():
    assert fill_plan(None, None, 3.03, 2.86, "finnhub", NOW) == {"eps_actual": 3.03, "eps_estimate": 2.86, "eps_source": "finnhub", "eps_fetched_at": NOW}
    assert fill_plan(3.03, None, 9.99, 2.86, "yfinance", NOW) == {"eps_estimate": 2.86, "eps_source": "yfinance", "eps_fetched_at": NOW}   # the actual stays
    assert fill_plan(3.03, 2.86, 9.99, 9.99, "finnhub", NOW) == {}
    assert fill_plan(None, None, None, None, "finnhub", NOW) == {}
    assert fill_plan(None, 2.86, None, 2.90, "finnhub", NOW) == {}                      # nothing new to say


def test_beat_or_miss_is_actual_against_estimate():
    assert eps_outcome(3.03, 2.86) == "beat" and eps_outcome(2.50, 2.86) == "miss" and eps_outcome(2.86, 2.86) == "meet"
    assert eps_outcome(None, 2.86) is None and eps_outcome(3.0, None) is None


def test_the_lookback_and_the_stale_rule_count_sessions():
    assert sessions_back(date(2026, 10, 5), 1) == date(2026, 10, 2) and sessions_back(date(2026, 10, 5), LOOKBACK_SESSIONS) == date(2026, 9, 21)
    assert not is_stale(date(2026, 10, 1), date(2026, 10, 5), None)          # two sessions between: still fresh
    assert is_stale(date(2026, 9, 30), date(2026, 10, 5), None)              # three sessions: stale
    assert not is_stale(date(2026, 9, 30), date(2026, 10, 5), 3.03)
    labels = [l for l, _ in refresh.STEPS]
    assert labels.index("EPS actuals (Finnhub)") == labels.index("Refresh earnings calendar (Finnhub)") + 1


@pytest.mark.asyncio
async def test_validate_warns_on_a_reported_event_without_its_eps():
    sym = "ZZEPS"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'EPS test', true)"), {"s": sym})
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                    SELECT gen_random_uuid(), id, 'earnings', CURRENT_DATE - 10, 'x', 'finnhub', true, '{}', now(), now() FROM tickers WHERE symbol = :s"""), {"s": sym})
            await s.commit()
        r = (await run_checks([check_eps_actuals_fresh]))[0]
        assert r.level == WARN and any(row.startswith(f"{sym} reported ") for row in r.rows)
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE events SET eps_actual = 1.0, eps_estimate = 0.9, eps_source = 'finnhub', eps_fetched_at = now() WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.commit()
        r = (await run_checks([check_eps_actuals_fresh]))[0]
        assert not any(sym in row for row in r.rows) and r.level in (PASS, WARN)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
