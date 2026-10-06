"""The next dividend is the declared per-payment amount, never the annual rate, and validate catches one that is."""
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.seed_dividends import FORWARD_BASIS_INTRINIO, FORWARD_BASIS_YFINANCE, PER_PAYMENT_BASES, _fetch_forward_sync
from app.scripts.validate_data import ERROR, check_next_dividend_amount, run_checks


def test_the_forward_fetch_reads_the_last_payment_not_the_rate(monkeypatch):
    import yfinance as yf
    class FakeTicker:
        def __init__(self, sym): pass
        info = {"exDividendDate": 1791936000, "dividendRate": 0.6, "lastDividendValue": 0.15}
    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    got = _fetch_forward_sync("MU")
    assert got == {"ex_date": date(2026, 10, 14), "last_payment": 0.15}
    assert "dividend_rate" not in got and FORWARD_BASIS_INTRINIO in PER_PAYMENT_BASES and FORWARD_BASIS_YFINANCE in PER_PAYMENT_BASES and "annual_rate" not in PER_PAYMENT_BASES


@pytest.mark.asyncio
async def test_validate_flags_an_annual_rate_stored_as_the_next_payment_and_accepts_a_declared_change():
    sym = "ZZDIV"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Dividend test', true)"), {"s": sym})
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2026-07-06', 'sec_dv', 100, 1, 1, 0.15, now())"), {"s": sym})
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                    SELECT gen_random_uuid(), id, 'ex_dividend', CURRENT_DATE + 8, 'x', 'yfinance', true, '{"dividend_amount": 0.6, "basis": "annual_rate"}', now(), now() FROM tickers WHERE symbol = :s"""), {"s": sym})
            await s.commit()
        r = (await run_checks([check_next_dividend_amount]))[0]
        assert r.level == ERROR and any(row.startswith(f"{sym} ") and "stored 0.6 (annual_rate) vs last paid 0.15" in row for row in r.rows)
        async with ScriptSessionLocal() as s:
            await s.execute(text("""UPDATE events SET metadata = '{"dividend_amount": 0.2, "basis": "per_share", "declared": true}' WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"""), {"s": sym})
            await s.commit()
        r = (await run_checks([check_next_dividend_amount]))[0]
        assert not any(row.startswith(f"{sym} ") for row in r.rows)                      # a declared change is accepted whatever its size
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
