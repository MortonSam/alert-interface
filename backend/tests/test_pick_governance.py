"""Ivy picks only a company-confirmed report date; a pick on a wrong date can be voided and stays in the ledger outside the
record; the calendar never leaves a past estimate standing or an estimate beside a confirmed date."""
import inspect
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.validate_data import ERROR, PASS, check_estimate_beside_confirmed, check_past_estimate_standing, run_checks
from app.scripts.void_pick import assess, targeted_report_day
from app.services.ivy_outcomes import IVY_OUTCOMES, REFUSED


async def _features_for(day: date):
    async def f(sym, db):
        return SimpleNamespace(event_date=day, symbol=sym)
    return f


async def _decide_pick(**kw):
    return SimpleNamespace(pick=True, direction="bullish", skip_reason=None, receipt={"reasoning": "test"})


# ── (a) the confirmed-date guard ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_pick_on_an_unconfirmed_date_is_refused_as_unconfirmed_date_and_the_receipt_names_the_date(monkeypatch):
    from app.routers import thesis
    import app.services.ivy_v2 as ivy
    monkeypatch.setattr(ivy, "compute_live_features", await _features_for(date(2026, 10, 14)))   # FDX holds no event on this day locally: an estimate at best
    monkeypatch.setattr(ivy, "decide", _decide_pick)
    async with ScriptSessionLocal() as s:
        out = await thesis._compute_alert_pick_v2("FDX", s, "nightly", False, datetime.now(timezone.utc).isoformat())
    assert out["outcome"] == "unconfirmed_date" and out["pick_id"] is None
    assert out["receipt"]["event_date"] == "2026-10-14" and out["receipt"]["event_confirmation"] == "estimated"
    assert "Ivy picks only a company-confirmed date" in out["note"]
    assert IVY_OUTCOMES["unconfirmed_date"]["category"] == REFUSED


@pytest.mark.asyncio
async def test_a_pick_on_a_company_confirmed_date_goes_through(monkeypatch):
    from app.routers import thesis
    import app.services.ivy_v2 as ivy
    async with ScriptSessionLocal() as s:
        row = (await s.execute(text("""SELECT t.symbol, e.event_date FROM events e JOIN tickers t ON t.id = e.ticker_id
                                       WHERE e.event_type = 'earnings' AND e.is_confirmed AND e.unresolved_since IS NULL AND e.event_date >= CURRENT_DATE
                                       ORDER BY e.event_date LIMIT 1"""))).first()
    if row is None:
        pytest.skip("no company-confirmed future report stored locally")
    monkeypatch.setattr(ivy, "compute_live_features", await _features_for(row.event_date))
    monkeypatch.setattr(ivy, "decide", _decide_pick)
    async with ScriptSessionLocal() as s:
        out = await thesis._compute_alert_pick_v2(row.symbol, s, "nightly", True, datetime.now(timezone.utc).isoformat())    # dry run: nothing written
    assert out["outcome"] == "picked" and out["receipt"]["event_confirmation"] == "confirmed" and out["receipt"]["event_date"] == row.event_date.isoformat()


# ── (b) void ─────────────────────────────────────────────────────────────────

def test_the_void_assessment_reads_the_targeted_day_from_the_exit_and_compares_it_with_the_actual_report():
    assert targeted_report_day(date(2026, 10, 19)) == date(2026, 10, 12)          # FDX: exit five sessions after the targeted Oct 12
    assert targeted_report_day(None) is None
    a = assess(pick_day=date(2026, 10, 5), exit_date=date(2026, 10, 19), actual=date(2026, 10, 28))
    assert a["targeted"] == date(2026, 10, 12) and a["actual_window_end"] == date(2026, 11, 4)
    assert a["exit_vs_window"] == "before the actual report" and a["sessions_target_to_actual"] == 12
    b = assess(pick_day=date(2026, 9, 21), exit_date=date(2026, 10, 5), actual=date(2026, 9, 29))             # CCL: a day early, exit inside the window
    assert b["targeted"] == date(2026, 9, 28) and b["exit_vs_window"] == "inside the actual window" and b["sessions_target_to_actual"] == 1
    c = assess(pick_day=date(2026, 9, 16), exit_date=date(2026, 9, 30), actual=date(2026, 9, 30))             # JBL: exit on the report day itself
    assert c["targeted"] == date(2026, 9, 23) and c["exit_vs_window"] == "inside the actual window"
    assert assess(pick_day=date(2026, 9, 2), exit_date=None, actual=date(2026, 10, 30))["targeted"] is None    # a v1 pick records no exit


def test_void_picks_are_outside_the_closer_and_carry_their_reason():
    from app.scripts import close_alert_picks
    from app.schemas.thesis import AlertPickLedgerItem
    src = inspect.getsource(close_alert_picks)
    assert 'AlertPick.status == "open"' in src and '"void"' not in src.replace("# ", "")      # the closer never selects a void pick
    assert "void_reason" in AlertPickLedgerItem.model_fields and "voided_at" in AlertPickLedgerItem.model_fields
    from app.routers import thesis
    assert 'is_void = r.status == "void"' in inspect.getsource(thesis)


# ── (c) the calendar ─────────────────────────────────────────────────────────

def _count(result) -> int:
    import re as _re
    m = _re.match(r"(\d+) ", result.message)
    return int(m.group(1)) if m and result.level != PASS else 0


@pytest.mark.asyncio
async def test_validate_errors_on_an_estimate_beside_a_confirmed_date_and_on_a_past_estimate_left_standing():
    sym = "ZZCAL"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Calendar test', true)"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            for d, conf in ((date.today() + timedelta(days=6), False), (date.today() + timedelta(days=22), True), (date.today() - timedelta(days=105), False)):
                await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                        VALUES (gen_random_uuid(), :t, 'earnings', :d, 'x', 'yfinance', :c, '{}', now(), now())"""), {"t": tid, "d": d, "c": conf})
            await s.commit()
        # counted, not listed: the local database holds many real rows of both kinds, and a check lists forty
        beside = (await run_checks([check_estimate_beside_confirmed]))[0]
        standing = (await run_checks([check_past_estimate_standing]))[0]
        assert beside.level == ERROR and standing.level == ERROR
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE events SET unresolved_since = CURRENT_DATE WHERE ticker_id = :t AND event_date < CURRENT_DATE"), {"t": tid})
            await s.execute(text("DELETE FROM events WHERE ticker_id = :t AND NOT is_confirmed AND event_date > CURRENT_DATE"), {"t": tid})
            await s.commit()
        beside2 = (await run_checks([check_estimate_beside_confirmed]))[0]
        standing2 = (await run_checks([check_past_estimate_standing]))[0]
        assert _count(beside) == _count(beside2) + 1 and _count(standing) == _count(standing2) + 1
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


def test_the_calendar_re_judges_every_past_estimate_still_standing_as_resolved():
    from app.scripts import refresh_earnings_calendar as rec
    src = inspect.getsource(rec)
    assert "Event.unresolved_since.is_(None) | (Event.event_date >= today - timedelta(days=PAST_LOOKBACK_DAYS))" in src
    assert rec.PAST_LOOKBACK_DAYS == 60
    from app.services.earnings_calendar import SAME_REPORT_DAYS
    assert SAME_REPORT_DAYS >= 45          # a confirmed date replaces an estimate this close (the FDX gap was 16 days)

# shares alert_picks rows with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="picks")
