"""Splits and ex-dividends from Intrinio's price adjustments: the ratio arithmetic, the bar readers, the comparison and the check."""
from datetime import date

import numpy as np
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.enums import DataSource
from app.scripts import seed_dividends, seed_splits
from app.scripts.compare_actions_intrinio import compare_dividends, compare_splits
from app.scripts.validate_data import CHECKS, ERROR, check_split_factor_match, run_checks
from app.services.corporate_actions import (MAX_FRACTIONAL_SIDE, MAX_RATIO_SIDE, dividends_from_adjustments, format_ratio, is_real_split_ratio,
                                            session_distance, split_ratio_from_intrinio, splits_from_adjustments, unmatched_splits)

SESSIONS = np.array([date(2026, 6, 22), date(2026, 6, 23), date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26), date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)], dtype=object)


def test_intrinio_price_factors_become_the_stored_shares_ratio():
    assert split_ratio_from_intrinio(0.1) == "10:1"          # NVDA 2024-06-10: split_ratio and factor both 0.1
    assert split_ratio_from_intrinio(0.25) == "4:1"          # CRWD 2026-07-02
    assert split_ratio_from_intrinio(3.0) == "1:3"           # DD 2026-06-24 reverse
    assert split_ratio_from_intrinio(5.0) == "1:5" and split_ratio_from_intrinio(1 / 3) == "3:1" and split_ratio_from_intrinio(0.04) == "25:1"
    assert split_ratio_from_intrinio(1.0, 0.25, 0.0) == "4:1"          # DXCM 2022-06-13: the split is in factor alone
    assert split_ratio_from_intrinio(1.0, 0.2, 0.0) == "5:1"           # FTNT 2022-06-23
    assert split_ratio_from_intrinio(2.0, 1.0095, 115.0) is None       # HON 2026-06-29: a separation, the price never halved
    assert split_ratio_from_intrinio(1.0, 0.9388, 1.8068) is None      # CMCSA 2026-01-05: a spin-off booked as a dividend
    assert split_ratio_from_intrinio(1.0, 0.9757, 0.0) is None         # BDX 2022-04-01: 41:40 is a spin-off factor, not a split
    assert split_ratio_from_intrinio(0.7587, 0.7587, 0.0) is None      # T 2022-04-11: 29:22, the WBD spin
    assert split_ratio_from_intrinio(1.5 ** -1, 1.5 ** -1, 0.0) == "3:2"
    assert split_ratio_from_intrinio(1.0) is None and split_ratio_from_intrinio(None) is None and split_ratio_from_intrinio("x") is None
    assert format_ratio(1.5) == "3:2" and format_ratio(0.5) == "1:2" and format_ratio(40 / 41) == "40:41"
    assert is_real_split_ratio("25:1") and is_real_split_ratio("1:50") and is_real_split_ratio("3:2") and is_real_split_ratio("5:4")
    assert not is_real_split_ratio("37:35") and not is_real_split_ratio("41:40") and not is_real_split_ratio("1:75") and not is_real_split_ratio("29:22")
    assert MAX_RATIO_SIDE == 50 and MAX_FRACTIONAL_SIDE == 10


def test_bar_rows_yield_splits_and_dividends_in_the_stored_shape():
    rows = [{"date": "2026-06-24", "split_ratio": 3.0, "factor": 3.0, "dividend": 0.0}, {"date": "2026-06-29", "split_ratio": 2.0, "factor": 1.0095, "dividend": 115.0},
            {"date": "2026-07-01", "split_ratio": 1.0, "factor": 0.95, "dividend": 20.3}, {"date": "2026-08-10", "split_ratio": 1.0, "factor": 0.9991, "dividend": 0.27},
            {"date": "2022-06-13", "split_ratio": 1.0, "factor": 0.25, "dividend": 0.0}]
    assert splits_from_adjustments(rows) == [{"date": date(2026, 6, 24), "split_ratio": "1:3", "intrinio_split_ratio": 3.0},
                                             {"date": date(2022, 6, 13), "split_ratio": "4:1", "intrinio_split_ratio": 0.25}]
    assert dividends_from_adjustments(rows) == [{"date": date(2026, 6, 29), "amount": 115.0}, {"date": date(2026, 7, 1), "amount": 20.3}, {"date": date(2026, 8, 10), "amount": 0.27}]


def test_the_seeders_read_the_store_write_intrinio_as_the_source_and_keep_the_shape():
    import inspect
    for mod in (seed_splits, seed_dividends):
        src = inspect.getsource(mod)
        assert "import yfinance" not in src and "yf.Ticker" not in src
        assert "FROM price_bars_shadow" in src and "price_adjustments(" in src and "DataSource.INTRINIO" in src
    assert DataSource.INTRINIO.value == "intrinio"
    assert 'title=f"{ticker.symbol} {split_ratio} Stock Split"' in inspect.getsource(seed_splits._upsert_split_event)
    assert '"split_ratio": split_ratio' in inspect.getsource(seed_splits._upsert_split_event)
    assert 'title=f"{ticker.symbol} Ex-Dividend"' in inspect.getsource(seed_dividends._upsert_dividend_event)
    assert 'meta["dividend_amount"] = dividend_amount' in inspect.getsource(seed_dividends._upsert_dividend_event)
    assert seed_dividends.DIVIDEND_BASIS == "per_share"


def test_the_comparison_matches_splits_within_one_session_and_names_every_disagreement():
    stored = [{"symbol": "DD", "date": date(2026, 6, 24), "split_ratio": "1:3"}, {"symbol": "HON", "date": date(2026, 6, 29), "split_ratio": "1:1"},
              {"symbol": "SPGI", "date": date(2026, 7, 1), "split_ratio": "37:35"}, {"symbol": "LATE", "date": date(2026, 6, 26), "split_ratio": "2:1"}]
    bars = [{"symbol": "DD", "date": date(2026, 6, 24), "split_ratio": "1:3", "intrinio_split_ratio": 3.0},
            {"symbol": "HON", "date": date(2026, 6, 29), "split_ratio": "1:2", "intrinio_split_ratio": 2.0},
            {"symbol": "LATE", "date": date(2026, 6, 29), "split_ratio": "2:1", "intrinio_split_ratio": 0.5},     # the next session: a match
            {"symbol": "NEW", "date": date(2026, 6, 30), "split_ratio": "4:1", "intrinio_split_ratio": 0.25}]
    r = compare_splits(stored, bars, SESSIONS)
    assert [x["symbol"] for x in r["agree"]] == ["DD", "LATE"]
    assert [(x["symbol"], x["intrinio_ratio"]) for x in r["ratio_differs"]] == [("HON", "1:2")]
    assert [x["symbol"] for x in r["yfinance_only"]] == ["SPGI"] and [x["symbol"] for x in r["intrinio_only"]] == ["NEW"]
    assert session_distance(SESSIONS, date(2026, 6, 26), date(2026, 6, 29)) == 1 and session_distance(SESSIONS, date(2026, 6, 24), date(2026, 6, 24)) == 0
    d = compare_dividends([{"symbol": "AAPL", "date": date(2026, 8, 10)}, {"symbol": "X", "date": date(2026, 8, 11)}, {"symbol": "F", "date": date(2026, 12, 1)}],
                          [{"symbol": "AAPL", "date": date(2026, 8, 10), "amount": 0.27}, {"symbol": "Y", "date": date(2026, 8, 12), "amount": 1.0}], date(2026, 10, 2))
    assert [x["symbol"] for x in d["agree"]] == ["AAPL"] and [x["symbol"] for x in d["yfinance_only"]] == ["X"] and d["not_comparable"] == 1
    assert [x["symbol"] for x in d["intrinio_only"]] == ["Y"]


def test_unmatched_splits_names_the_missing_factor_or_the_other_ratio():
    stored = [{"symbol": "DD", "date": date(2026, 6, 24), "split_ratio": "1:3"}, {"symbol": "HON", "date": date(2026, 6, 29), "split_ratio": "1:1"},
              {"symbol": "SPGI", "date": date(2026, 7, 1), "split_ratio": "37:35"}]
    bars = [{"symbol": "DD", "date": date(2026, 6, 25), "split_ratio": "1:3"}, {"symbol": "HON", "date": date(2026, 6, 29), "split_ratio": "1:2"}]
    out = unmatched_splits(stored, bars, SESSIONS)
    assert out == ["HON 2026-06-29 1:1: the shadow bars say 1:2", "SPGI 2026-07-01 37:35: no split factor on the shadow bars within one session"]
    assert unmatched_splits([stored[0]], [{"symbol": "DD", "date": date(2026, 6, 26), "split_ratio": "1:3"}], SESSIONS)          # two sessions away: unmatched
    assert check_split_factor_match in CHECKS


@pytest.mark.asyncio
async def test_the_check_errors_on_a_split_the_bars_do_not_carry_and_passes_once_they_do():
    sym = "ZZSPL"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Split test', true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata)
                                    VALUES (gen_random_uuid(), :t, 'split', '2026-06-24', 'ZZSPL 4:1 Stock Split', 'intrinio', true, '{"split_ratio": "4:1"}')"""), {"t": tid})
            await s.commit()
        r = (await run_checks([check_split_factor_match]))[0]
        assert r.level == ERROR and any(x.startswith(f"{sym} 2026-06-24 4:1: no split factor") for x in r.rows)
        async with ScriptSessionLocal() as s:
            await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, open, high, low, close, volume, factor, split_ratio, dividend, fetched_at)
                                    VALUES (:s, '2026-06-25', 'sec_zz', 10, 10, 10, 10, 1, 0.25, 0.25, 0, now())"""), {"s": sym})     # the next session: within one
            await s.commit()
        r = (await run_checks([check_split_factor_match]))[0]
        assert not any(sym in x for x in r.rows)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
