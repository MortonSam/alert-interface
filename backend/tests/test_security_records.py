"""Every active ticker resolves to exactly one Intrinio record per date, by id; the map is checked, not assumed."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import refresh
from app.scripts.build_security_records import STEP_LABEL, upsert
from app.scripts.validate_data import CHECKS, ERROR, PASS, check_figi_change, check_security_record_coverage, run_checks
from app.services.security_records import (
    CURRENT, PREDECESSOR, PREDECESSORS, STORED, STORED_HISTORY, STORED_HISTORY_ROWS, STORED_START,
    Record, coverage_problems, plan_records, resolve,
)
from app.services.trading_calendar import is_trading_day

TODAY = date(2026, 10, 1)


def body(id="sec_agjrgj", figi="BBG000B9Y5X2", first="1980-12-12", last="2026-10-01"):
    return {"id": id, "figi": figi, "composite_figi": "BBG000B9XRY4", "name": "Apple Inc",
            "first_stock_price": first, "last_stock_price": last}


# ── plan_records ──────────────────────────────────────────────────────────────

def test_a_plain_ticker_gets_one_current_row_from_its_first_price_date():
    rows = plan_records("AAPL", body())
    assert rows == [Record("AAPL", "sec_agjrgj", "BBG000B9Y5X2", "BBG000B9XRY4", "Apple Inc", date(1980, 12, 12), None, CURRENT, "intrinio")]


def test_a_redomiciled_ticker_gets_its_predecessor_then_its_current_record_from_the_declared_day():
    rows = plan_records("OKE", body(id="sec_g2d35l", figi="BBG024W7VJL9", first="2026-09-15"))
    assert [r.role for r in rows] == [PREDECESSOR, CURRENT]
    pred, cur = rows
    assert pred.intrinio_security_id == "sec_ybYl7z" and pred.valid_to == date(2026, 9, 14)
    assert cur.valid_from == date(2026, 9, 15) and cur.valid_to is None


def test_psky_keeps_its_stored_history_before_the_current_record():
    rows = plan_records("PSKY", body(id="sec_z9qYDq", figi="BBG01WF624M3", first="2025-08-07"))
    hist, cur = rows
    assert hist.role == STORED_HISTORY and hist.source == STORED and hist.intrinio_security_id is None
    assert (hist.valid_from, hist.valid_to) == (STORED_START, date(2025, 8, 6))
    assert cur.valid_from == date(2025, 8, 7)


def test_every_declared_predecessor_hands_over_with_no_session_between():
    """The declared spans are data: each predecessor's last day and the successor's first day enclose no session."""
    for sym, p in PREDECESSORS.items():
        assert p["valid_to"] < p["current_from"], sym
        d = p["valid_to"]
        while (d := d.fromordinal(d.toordinal() + 1)) < p["current_from"]:
            assert not is_trading_day(d), f"{sym}: {d} is a session nobody covers"
    for sym, s in STORED_HISTORY_ROWS.items():
        assert s["valid_to"] < s["current_from"], sym
        assert not any(is_trading_day(date.fromordinal(o)) for o in range(s["valid_to"].toordinal() + 1, s["current_from"].toordinal())), sym


# ── resolve and coverage_problems ─────────────────────────────────────────────

def two_rows():
    return [Record("TEL", "sec_gAD5Jy", "f1", None, None, date(2007, 6, 14), date(2024, 9, 27), PREDECESSOR, "intrinio"),
            Record("TEL", "sec_zq8bAk", "f2", None, None, date(2024, 9, 30), None, CURRENT, "intrinio")]


def test_resolve_names_the_one_record_on_a_date_and_none_where_there_is_none():
    rows = two_rows()
    assert resolve(rows, date(2024, 9, 27)).intrinio_security_id == "sec_gAD5Jy"
    assert resolve(rows, date(2024, 9, 30)).intrinio_security_id == "sec_zq8bAk"
    assert resolve(rows, date(2024, 9, 28)) is None            # a Saturday no row covers
    assert resolve(rows, date(2000, 1, 1)) is None


def test_contiguous_records_cover_the_window_and_a_weekend_handover_is_not_a_gap():
    assert coverage_problems(two_rows(), date(2021, 7, 1), TODAY) == []


def test_a_gap_holding_a_session_is_a_problem_and_so_is_an_overlap_or_no_current_row():
    rows = two_rows()
    rows[1] = Record("TEL", "sec_zq8bAk", "f2", None, None, date(2024, 10, 2), None, CURRENT, "intrinio")
    assert coverage_problems(rows, date(2021, 7, 1), TODAY) == ["gap 2024-09-28..2024-10-01"]
    rows[1] = Record("TEL", "sec_zq8bAk", "f2", None, None, date(2024, 9, 27), None, CURRENT, "intrinio")
    assert any(p.startswith("predecessor 2007-06-14..2024-09-27 overlaps current") for p in coverage_problems(rows, date(2021, 7, 1), TODAY))
    only_pred = [two_rows()[0]]
    probs = coverage_problems(only_pred, date(2021, 7, 1), TODAY)
    assert "no current record" in probs and "gap 2024-09-28..2026-10-01" in probs
    assert coverage_problems([], date(2021, 7, 1), TODAY) == ["no record at all for 2021-07-01..2026-10-01"]


def test_a_current_record_starting_after_the_oldest_stored_row_is_a_gap():
    rows = [Record("CEG", "sec_x", "f", None, None, date(2022, 2, 2), None, CURRENT, "intrinio")]
    assert coverage_problems(rows, date(2022, 1, 26), TODAY) == ["gap 2022-01-26..2022-02-01"]


# ── the nightly step and the checks are wired ─────────────────────────────────

def test_the_build_runs_nightly_before_validate_with_a_timeout():
    labels = [label for label, _ in refresh.STEPS]
    assert STEP_LABEL in labels and labels.index(STEP_LABEL) < labels.index("Validate data")
    assert refresh.STEP_TIMEOUTS[STEP_LABEL] >= 600
    assert check_security_record_coverage in CHECKS and check_figi_change in CHECKS


# ── the FIGI change path, against the database ────────────────────────────────

@pytest.mark.asyncio
async def test_a_moved_ticker_keeps_its_stored_figi_records_the_new_one_and_fails_figi_change():
    sym = "ZZFIGI"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": sym})
            await s.commit()
        async with ScriptSessionLocal() as s:
            rows = plan_records(sym, body(id="sec_old", figi="BBG_OLD", first="2020-01-02"))
            assert await upsert(s, rows, body(id="sec_old", figi="BBG_OLD")) == (1, 0, False)
            await s.commit()
        async with ScriptSessionLocal() as s:
            rows = plan_records(sym, body(id="sec_new", figi="BBG_NEW", first="2020-01-02"))
            assert await upsert(s, rows, body(id="sec_new", figi="BBG_NEW")) == (0, 1, True)
            await s.commit()
        async with ScriptSessionLocal() as s:
            row = (await s.execute(text("SELECT figi, figi_seen, intrinio_security_id, checked_at FROM security_records WHERE symbol = :s"), {"s": sym})).one()
        assert row.figi == "BBG_OLD" and row.figi_seen == "BBG_NEW" and row.checked_at is not None
        result = (await run_checks([check_figi_change]))[0]
        assert result.level == ERROR and any(r.startswith(f"{sym}: stored FIGI BBG_OLD, Intrinio now BBG_NEW") for r in result.rows)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": sym})
            await s.commit()


@pytest.mark.asyncio
async def test_figi_change_passes_when_every_current_record_still_has_its_figi():
    """The local build wrote every current record with figi == figi_seen; nothing synthetic is left behind."""
    result = (await run_checks([check_figi_change]))[0]
    assert result.level == PASS, result.message
