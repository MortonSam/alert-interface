"""The one-year price change has one rule (services/one_year, Sam's item 8, 2026-11-16): the latest stored close against the close of
the last session on or before the same calendar date a year earlier (Feb 29 -> Feb 28), split-adjusted by the recorded split history
(events of type split), dividends and spin-off distributions not added back. The walkthrough, its sector medians, step 5's year-earlier close and the ticker page's 1Y header all read it,
and no second one-year computation exists."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import one_year as OY
from app.services import price_bars
from app.services import walkthrough_data as D

APP = Path(__file__).resolve().parents[1] / "app"


def _weekdays(a: date, b: date, skip: set[date] = frozenset()) -> list[date]:
    out, d = [], a
    while d <= b:
        if d.weekday() < 5 and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


# ── the rule, pure ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_same_date_a_year_earlier_and_leap_day():
    assert OY.year_earlier(date(2026, 11, 16)) == date(2025, 11, 16)
    assert OY.year_earlier(date(2028, 2, 29)) == date(2027, 2, 28)       # Feb 29 -> Feb 28
    assert OY.year_earlier(date(2029, 2, 28)) == date(2028, 2, 28)       # never Feb 29 from a Feb 28


def test_a_weekend_start_takes_the_friday_before():
    s = [(date(2025, 11, 13), 90.0), (date(2025, 11, 14), 100.0), (date(2025, 11, 17), 105.0), (date(2026, 11, 16), 110.0)]
    oy = OY.one_year_change(s)                                            # Nov 16, 2025 is a Sunday
    assert oy["start_date"] == date(2025, 11, 14) and oy["start_close"] == 100.0
    assert oy["end_date"] == date(2026, 11, 16) and oy["end_close"] == 110.0 and abs(oy["pct"] - 10.0) < 1e-9 and abs(oy["change"] - 10.0) < 1e-9


def test_a_holiday_start_takes_the_session_before_and_the_same_date_is_taken_when_it_traded():
    thanksgiving = date(2025, 11, 27)
    s = [(d, 100.0 + i) for i, d in enumerate(_weekdays(date(2025, 11, 20), date(2025, 12, 5), {thanksgiving}))] + [(date(2026, 11, 27), 200.0)]
    assert OY.one_year_change(s)["start_date"] == date(2025, 11, 26)
    s2 = s[:-1] + [(date(2026, 11, 26), 200.0)]
    assert OY.one_year_change(s2)["start_date"] == date(2025, 11, 26)    # the date itself when it is a session


def test_leap_day_end_starts_from_feb_28_or_before():
    s = [(date(2027, 2, 25), 50.0), (date(2027, 2, 26), 60.0), (date(2027, 3, 1), 70.0), (date(2028, 2, 29), 90.0)]
    oy = OY.one_year_change(s)                                            # Feb 28, 2027 is a Sunday: the Friday before
    assert oy["start_date"] == date(2027, 2, 26) and abs(oy["pct"] - 50.0) < 1e-9


def test_a_split_between_the_dates_is_adjusted_by_the_recorded_split():
    # raw closes: 200 before a 2:1 split effective Jun 1, 2026 (ratio 2, new for old), 110 after
    rows = [(date(2025, 11, 14), 200.0), (date(2026, 6, 1), 104.0), (date(2026, 11, 16), 110.0)]
    s = OY.split_adjusted(rows, [(date(2026, 6, 1), 2.0)])
    assert s == [(date(2025, 11, 14), 100.0), (date(2026, 6, 1), 104.0), (date(2026, 11, 16), 110.0)]
    assert abs(OY.one_year_change(s)["pct"] - 10.0) < 1e-9
    # a reverse split (1:5, ratio 0.2) adjusts the other way; a split before the start changes nothing between the dates
    assert OY.split_adjusted([(date(2025, 1, 2), 2.0), (date(2025, 6, 2), 10.0)], [(date(2025, 6, 2), 0.2)])[0] == (date(2025, 1, 2), 10.0)
    assert OY.split_adjusted(rows, [(date(2024, 1, 2), 4.0)]) == rows
    # a split whose ratio is unreadable: nothing before it is used, so no change reaches across it
    assert OY.one_year_change(OY.split_adjusted(rows, [(date(2026, 6, 1), None)])) is None


# ── spin-offs: what a holder experienced (Sam, 2026-11-16) ──────────────────────────────────────────────────────────────────

SPIN = date(2026, 6, 1)


def _spun(value, open_, bar_ratio=1.0):
    """Raw bars around a spin-off on Jun 1, 2026: 200 a year before, 200 the session before, then the open and 110 after."""
    return [(date(2025, 11, 14), 200.0, 200.0, 0.0, 1.0), (date(2026, 5, 29), 200.0, 200.0, 0.0, 1.0),
            (SPIN, 105.0, open_, value, bar_ratio), (date(2026, 11, 16), 110.0, 110.0, 0.0, 1.0)]


def test_a_spin_off_is_not_a_price_drop():
    # 200 before; the spun-off shares worth 90 a share (booked on the ex-date bar, the open gapped 92): a holder kept 110 + 90 = 200 of value
    s = OY.holder_adjusted(_spun(90.0, 108.0), [], [SPIN])
    assert s[0] == (date(2025, 11, 14), pytest.approx(110.0)) and s[2] == (SPIN, 105.0)        # 200 x (200 - 90) / 200
    assert OY.one_year_change(s)["pct"] == pytest.approx(0.0)
    assert OY.one_year_change(OY.holder_adjusted(_spun(90.0, 108.0), [], []))["pct"] == pytest.approx(-45.0)   # unrecorded: a drop, as before


def test_a_spin_off_value_the_data_cannot_confirm_leaves_the_year_absent():
    assert OY.one_year_change(OY.holder_adjusted(_spun(30.0, 108.0), [], [SPIN])) is None        # booked 30, the open gapped 92
    assert OY.one_year_change(OY.holder_adjusted(_spun(90.0, 108.0, 2.0), [], [SPIN])) is None   # a ratio on the bar (HON, Jun 29)
    assert OY.one_year_change(OY.holder_adjusted(_spun(0.0, 108.0), [], [SPIN])) is None         # no value booked
    assert OY.one_year_change(OY.holder_adjusted(_spun(250.0, 108.0), [], [SPIN])) is None       # more than the close
    # closes from the spin-off on still stand
    assert OY.holder_adjusted(_spun(30.0, 108.0), [], [SPIN]) == [(SPIN, 105.0), (date(2026, 11, 16), 110.0)]


def test_a_records_own_ratio_can_confirm_the_value_when_the_open_did_not():
    # SPGI, Jul 1, 2026: 20.30 booked against a 7.68 gap at the open; its record's 37:35 implies 2/37 of the close, 22.01
    bars = [(date(2025, 7, 1), 380.0, 380.0, 0.0, 1.0), (date(2026, 6, 30), 407.26, 406.58, 0.0, 1.0),
            (date(2026, 7, 1), 414.97, 399.58, 20.3, 1.0), (date(2026, 7, 2), 439.89, 423.26, 0.0, 1.0)]
    assert OY.holder_adjusted(bars, [], [date(2026, 7, 2)])[0][0] == date(2026, 7, 1)          # the filing's record alone: not confirmed
    s = OY.holder_adjusted(bars, [], [(date(2026, 7, 1), 37 / 35), date(2026, 7, 2)])          # both records: counted once
    assert s[1][1] == pytest.approx(407.26 - 20.3) and s[0][1] == pytest.approx(380.0 * (407.26 - 20.3) / 407.26)


def test_a_spin_off_and_a_split_together_and_one_before_the_bars():
    # a 2:1 split on Mar 2 and a spin-off on Jun 1: the value booked after the split is already in today's shares
    bars = [(date(2025, 11, 14), 400.0, 400.0, 0.0, 1.0), (date(2026, 2, 27), 400.0, 400.0, 0.0, 1.0)] + _spun(90.0, 108.0)[1:]
    s = OY.holder_adjusted(bars, [(date(2026, 3, 2), 2.0)], [SPIN])
    assert s[0][1] == pytest.approx(110.0) and OY.one_year_change(s)["pct"] == pytest.approx(0.0)
    # a spin-off before the bars begin, with no bar beside it, changes nothing
    assert OY.holder_adjusted(_spun(90.0, 108.0), [], [date(2024, 1, 2)]) == OY.holder_adjusted(_spun(90.0, 108.0), [], [])


def test_step_5_has_no_pe_year_across_a_spin_off():
    src = (APP / "scripts" / "build_walkthroughs.py").read_text()
    assert 'a["kind"] == "spin_off"' in src and "year = None if spun else D.pe_year(" in src


def test_absent_rather_than_estimated():
    assert OY.one_year_change([]) is None
    assert OY.one_year_change([(date(2026, 1, 5), 10.0), (date(2026, 11, 16), 12.0)]) is None      # bars begin after the start date
    s = [(date(2025, 10, 31), 10.0), (date(2026, 11, 16), 12.0)]                                     # 16 days before the target: a halt
    assert OY.one_year_change(s) is None
    assert OY.one_year_change([(date(2025, 11, 14), 10.0), (date(2026, 11, 16), 12.0)], end=date(2026, 11, 13)) is None   # not a session


def test_an_end_session_aligns_series():
    s = [(date(2025, 11, 13), 100.0), (date(2025, 11, 14), 105.0), (date(2026, 11, 13), 120.0), (date(2026, 11, 16), 130.0)]
    oy = OY.one_year_change(s, end=date(2026, 11, 13))
    assert oy["end_close"] == 120.0 and oy["start_date"] == date(2025, 11, 13) and abs(oy["pct"] - 20.0) < 1e-9


# ── the walkthrough reads it ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_walkthrough_year_calendar_and_sector_median_follow_the_rule():
    days = _weekdays(date(2025, 9, 1), date(2026, 11, 13))
    spy = [(d, 100.0 + i * 0.1) for i, d in enumerate(days)]
    cal = D.year_calendar(spy)
    assert cal[0] == date(2025, 11, 13) and cal[-1] == date(2026, 11, 13)
    tickers = {f"S{i}": {"index_member": True, "sector": "Tech"} for i in range(3)}
    closes = {f"S{i}": [(d, 50.0 * (1 + 0.1 * i) ** (j / len(days))) for j, d in enumerate(days)] for i in range(3)}
    sec = D.sector_changes(tickers, closes, spy)["Tech"]
    want = sorted(OY.one_year_change(closes[f"S{i}"])["pct"] for i in range(3))[1]
    assert sec["change_1y"] == round(want, 1) and sec["start"] == date(2025, 11, 13)
    assert D.year_change(spy)[1:] == (date(2025, 11, 13), date(2026, 11, 13))


def test_step_5s_year_earlier_close_is_the_one_year_start_session():
    q = lambda end, eps: {"end": end, "start": end - timedelta(days=90), "eps": eps, "filed": end + timedelta(days=30)}
    ends = [date(2024, 10, 27), date(2025, 1, 26), date(2025, 4, 27), date(2025, 7, 27), date(2025, 10, 26), date(2026, 1, 25), date(2026, 4, 26), date(2026, 7, 26)]
    quarters = [q(e, 1.0) for e in ends]
    snap = {"status": "ok", "as_of_date": date(2026, 11, 16), "window_end": date(2026, 7, 26), "trailing_eps": 5.0, "price": 120.0}
    bars = [(date(2025, 11, 13), 90.0), (date(2025, 11, 14), 100.0), (date(2025, 11, 17), 95.0), (date(2026, 11, 16), 120.0)]
    y = D.pe_year(bars, quarters, snap)
    assert y["then"] == date(2025, 11, 14) and y["price_pct"] == 20.0 and y["pe_then"] == 25.0


# ── the ticker page's 1Y header reads it from the chart answer ──────────────────────────────────────────────────────────────

SYM = "ZZOY"


@pytest.mark.asyncio
async def test_the_one_year_chart_carries_the_rules_change_from_the_stored_bars():
    days = _weekdays(date(2025, 11, 3), date(2026, 11, 16))
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": SYM})
        for d in days:
            close, factor, ratio = (200.0, 1.0, 1.0) if d < date(2026, 6, 1) else (110.0, 1.0, 1.0)
            if d == date(2026, 6, 1):
                factor, ratio = 0.5, 0.5                                  # a 2:1 split, recorded below
            if d == date(2026, 3, 2):
                factor = 0.99                                             # a dividend: in the chart's line, not in the one-year change
            if d == date(2026, 9, 1):
                factor, ratio = 1.01, 2.0                                 # a spin-off booked as a "split" on the bar (HON, 2026-06-29): no split
            await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, open, high, low, close, volume, factor, split_ratio, dividend, fetched_at)
                                    VALUES (:s, :d, 'sec_zzoy', :c, :c, :c, :c, 1000, :f, :r, 0, :t)"""),
                            {"s": SYM, "d": d, "c": close, "f": factor, "r": ratio, "t": datetime.now(timezone.utc)})
        await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
        await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'One year test', true)"), {"s": SYM})
        await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                SELECT gen_random_uuid(), id, 'split', '2026-06-01', 'ZZOY 2:1 Stock Split', 'yfinance', true, '{"split_ratio": "2:1"}'::jsonb, now(), now()
                                FROM tickers WHERE symbol = :s"""), {"s": SYM})
        await s.commit()
    try:
        chart = price_bars.chart_history_daily_sync(SYM, "1y", date(2026, 11, 16))
        oy = chart["one_year"]
        assert oy["start_date"] == date(2025, 11, 14) and oy["end_date"] == date(2026, 11, 16)   # Nov 16, 2025 was a Sunday
        assert abs(oy["start_close"] - 100.0) < 1e-9 and abs(oy["pct"] - 10.0) < 1e-9
        assert chart["history"][0]["date"] == "2025-11-14" and chart["history"][-1]["date"] == "2026-11-16"
        # the line is the header's closes: it cannot disagree with the figure
        assert chart["history"][0]["close"] == oy["start_close"] and chart["history"][-1]["close"] == oy["end_close"]
        assert chart["start_price"] == oy["start_close"]
        assert price_bars.one_year_sync(SYM, date(2026, 11, 16)) == oy
        async with ScriptSessionLocal() as s:
            assert await price_bars.holder_closes(s, SYM, date(2025, 11, 1)) == price_bars.holder_closes_sync(SYM, date(2025, 11, 1))
        # a recorded spin-off whose value the bars do not book: the header is absent, and the line holds only what follows it
        async with ScriptSessionLocal() as s:
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                    SELECT gen_random_uuid(), id, 'other', '2026-08-03', 'ZZOY spin off: Test', 'edgar', true, '{"corporate_action": "spin_off"}'::jsonb, now(), now()
                                    FROM tickers WHERE symbol = :s"""), {"s": SYM})
            await s.commit()
        chart = price_bars.chart_history_daily_sync(SYM, "1y", date(2026, 11, 16))
        assert chart["one_year"] is None and chart["history"][0]["date"] == "2026-08-03"
        assert "one_year" not in price_bars.chart_history_daily_sync(SYM, "6mo", date(2026, 11, 16))
        from app.routers.tickers import _one_year_read
        from app.services.one_year import ONE_YEAR_VERSION
        served = _one_year_read(oy)
        assert served.start_date == "2025-11-14" and served.pct == 10.0 and served.version == ONE_YEAR_VERSION
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": SYM})
            await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
            await s.commit()


# ── no second rule ──────────────────────────────────────────────────────────────────────────────────────────────────────────

# a one-year price change worked out any other way: 252 or 253 sessions back from the end, a session count named for the year in a
# change, or a close picked 365/366 days before
SECOND_RULE = [
    re.compile(r"\[\s*-\s*(?:253|252\s*-\s*1|YEAR_SESSIONS\s*-\s*1)\s*[\]:]"),
    re.compile(r"\bchange\([^)]*\b(?:252|YEAR_SESSIONS)\b"),
    re.compile(r"\b(?:pct_change|shift)\(\s*252\s*\)"),
    re.compile(r"(?:close|bars?)\b.*timedelta\(days=(?:36[56]|PE_YEAR_DAYS)\)|timedelta\(days=(?:36[56]|PE_YEAR_DAYS)\).*\b(?:close|bars?)\b"),
]
YEAR_SESSIONS_ALLOWED = {("services/walkthrough_data.py", "YEAR_SESSIONS = 252"), ("services/walkthrough_data.py", "def ordinary_move(")}


def test_no_other_one_year_change_exists():
    hits = []
    for p in sorted(APP.rglob("*.py")):
        rel = p.relative_to(APP).as_posix()
        if "/cache/" in f"/{rel}" or rel == "services/one_year.py":
            continue
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            code = line.split("#", 1)[0]
            if any(r.search(code) for r in SECOND_RULE):
                hits.append(f"{rel}:{n}: {line.strip()}")
            if "YEAR_SESSIONS" in code and not any(rel == f and s in code for f, s in YEAR_SESSIONS_ALLOWED):
                hits.append(f"{rel}:{n}: {line.strip()}")
    assert not hits, "a one-year change outside services/one_year:\n" + "\n".join(hits)


def test_every_one_year_site_reads_the_rule():
    for rel, call in (("services/walkthrough.py", "year_change("), ("services/walkthrough_data.py", "one_year_change("),
                      ("services/walkthrough_data.py", "start_session("), ("services/price_bars.py", "one_year_sync("),
                      ("routers/tickers.py", "_one_year_read(")):
        assert call in (APP / rel).read_text(), f"{rel} no longer calls {call}"
    front = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "priceHeader.ts"
    if front.exists():                                                    # the page shows the API's figure, never recomputes it
        assert "one_year" in front.read_text()
