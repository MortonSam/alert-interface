"""Part three of the Oct 6 block: the move comparison every page shares, the EDGAR report history by CIK and alias, the
pre-listing cleanup's selection, and the dividend declaration parser on Micron's Sep 30, 2026 release."""
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.cleanup_prelisting_reactions import SELECT_SQL
from app.scripts.seed_report_history import HISTORY_YEARS, report_dates, timing_from_acceptance
from app.services.dividend_declarations import parse_declaration
from app.services.move_comparison import LESS_RATIO, MIN_REPORTS, MORE_RATIO, compare_moves, comparison_sentence

MU_RELEASE = ("Micron Technology, Inc. (Nasdaq: MU) today announced results for its fourth quarter and full year of fiscal 2026. "
              "The Board of Directors declared a quarterly dividend of $0.15 per share, payable in cash on October 29, 2026, to shareholders "
              "of record as of the close of business on October 14, 2026. Micron will host a conference call.")


def test_compare_moves_thresholds_and_the_sentence():
    assert (MORE_RATIO, LESS_RATIO, MIN_REPORTS) == (1.2, 0.8, 8)
    assert compare_moves(6.0, 4.0) == "more than usual" and compare_moves(4.7, 4.0) == "about its usual" and compare_moves(3.1, 4.0) == "less than usual"
    assert compare_moves(4.8, 4.0) == "about its usual" and compare_moves(3.2, 4.0) == "about its usual"        # the edges stay usual
    assert comparison_sentence(6.0, 4.0, date(2026, 10, 5)) == "Options price a ±6.0% move; it has moved ±4.0% on a typical report, more than usual (chain Oct 5, 2026)."


def test_micron_declaration_parses_amount_payable_record_and_filing_date():
    d = parse_declaration(MU_RELEASE, date(2026, 9, 30))
    assert d == {"amount": 0.15, "payable_date": date(2026, 10, 29), "record_date": date(2026, 10, 14), "declared_on": date(2026, 9, 30)}
    other = "The Board declared a regular quarterly cash dividend of $1.05 per common share payable December 15, 2026 to stockholders of record on November 28, 2026."
    assert parse_declaration(other, date(2026, 10, 2))["record_date"] == date(2026, 11, 28)
    third = parse_declaration("declared a dividend of $0.50 per share, payable on or about January 5, 2027 to holders of record at the close of business December 10, 2026.", date(2026, 10, 2))
    assert third["payable_date"] == date(2027, 1, 5) and third["record_date"] == date(2026, 12, 10)
    assert parse_declaration("Revenue was $2.1 billion. No dividend was declared.", date(2026, 9, 30)) is None
    assert parse_declaration("The company declared a dividend of $0.50 per share earlier this year.", date(2026, 9, 30)) is None   # no dates: not a declaration we can use


def test_report_history_reads_item_2_02_filings_with_timing_from_the_acceptance_time():
    recs = [{"filing_date": "2026-07-22", "acceptance": "2026-07-22T20:05:12.000Z", "items": "2.02,9.01", "accession": "a"},     # 16:05 New York: after the close
            {"filing_date": "2026-07-22", "acceptance": "2026-07-22T20:05:12.000Z", "items": "2.02", "accession": "dup"},
            {"filing_date": "2026-04-28", "acceptance": "2026-04-28T15:02:00.000Z", "items": "2.02,9.01", "accession": "b"},     # 11:02 New York: inside the session
            {"filing_date": "2026-02-05", "acceptance": "2026-02-05T10:55:00.000Z", "items": "2.02", "accession": "c"},     # 06:55 New York: before the open
            {"filing_date": "2026-01-15", "acceptance": "2026-01-15T21:10:00.000Z", "items": "5.02", "accession": "x"},     # not a results filing
            {"filing_date": "2019-04-28", "acceptance": "2019-04-28T21:00:00.000Z", "items": "2.02", "accession": "old"}]
    out = report_dates(recs, date(2026, 10, 6))
    assert [(r["date"].isoformat(), r["timing"], r["accession"]) for r in out] == [("2026-07-22", "amc", "a"), ("2026-04-28", "unknown", "b"), ("2026-02-05", "bmo", "c")]
    assert HISTORY_YEARS == 5 and timing_from_acceptance(None) == "unknown"


@pytest.mark.asyncio
async def test_cleanup_selects_only_all_null_rows_before_the_first_bar():
    sym = "ZZPRE"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Pre-listing test', true)"), {"s": sym})
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2024-07-08', 'sec_pre', 10, 1, 1, 0, now())"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, created_at) VALUES (gen_random_uuid(), :t, 'fomc', '2022-03-16', now())"), {"t": tid})          # all null, pre-listing: goes
            await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, created_at) VALUES (gen_random_uuid(), :t, 'fomc', '2022-05-04', 1.0, now())"), {"t": tid})   # has a move: stays
            await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, created_at) VALUES (gen_random_uuid(), :t, 'fomc', '2024-09-18', now())"), {"t": tid})          # after listing: stays
            await s.commit()
            rows = (await s.execute(text(SELECT_SQL))).mappings().all()
        mine = [r for r in rows if r["symbol"] == sym]
        assert [r["event_date"].isoformat() for r in mine] == ["2022-03-16"]
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


@pytest.mark.asyncio
async def test_the_calendar_rows_carry_the_comparison_fields_or_none():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/discover/reporting-soon?days=14&limit=10")).json()
    for item in body["items"]:
        assert set(item) >= {"implied_move_pct", "chain_date", "typical_move_pct", "typical_n", "move_comparison", "comparison"}
        if item["comparison"]:
            assert item["typical_n"] >= MIN_REPORTS and item["chain_date"] and item["move_comparison"] in item["comparison"]
            assert f"±{item['implied_move_pct']:.1f}% move" in item["comparison"]
        else:
            assert item["move_comparison"] is None
