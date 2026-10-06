"""The three Oct 6 failures: a dry-run pick never reads an unset structure (FDX), a rename never moves a reaction dated
before the kept symbol's first bar (VMRK), and an RV snapshot is dated by its bar and recomputed for the trailing
sessions (CTVA)."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import compute_rv_ranks as rv
from app.scripts.validate_data import ERROR, PASS, WARN, check_reactions_after_first_bar, check_rv_snapshot_unchanged, run_checks


# ── 1. FDX ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_would_be_pick_evaluated_in_dry_run_returns_picked_with_no_structure(monkeypatch):
    """FDX held an open pick, so the v2 path ran as a dry run; the engine still said pick, and the final return read
    `structure`, which only the write path set. Now it is None on a dry run and the call returns."""
    from app.routers import thesis
    import app.services.ivy_v2 as ivy
    monkeypatch.setattr(ivy, "compute_live_features", _fake_features)
    monkeypatch.setattr(ivy, "decide", _fake_decide_pick)
    async with ScriptSessionLocal() as s:
        out = await thesis._compute_alert_pick_v2("FDX", s, "nightly", True, datetime.now(timezone.utc).isoformat())
    assert out["outcome"] == "picked" and out["pick_id"] is None and out["structure"] is None
    src = __import__("inspect").getsource(thesis._compute_alert_pick_v2)
    assert "structure: dict | None = None" in src


async def _fake_features(sym, db):
    return SimpleNamespace(event_date=date(2026, 10, 14), symbol=sym)


async def _fake_decide(**kw):
    return SimpleNamespace(pick=True, direction="bullish", skip_reason=None, receipt={"reasoning": "test"})


_fake_decide_pick = _fake_decide


def test_the_auto_pick_loop_records_a_raising_ticker_and_moves_on_and_takes_a_symbol_filter():
    import inspect
    from app.scripts import auto_pick
    src = inspect.getsource(auto_pick._run)
    assert "except Exception as exc:" in src and "failures.append(" in src and '_log_evaluation(session, sym, "error"' in src
    assert "if only:" in src and "c.symbol in only" in src
    assert "--symbols=" in inspect.getsource(auto_pick.main)


# ── 2. VMRK ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_errors_on_a_reaction_dated_before_the_first_bar_and_the_merge_refuses_one():
    from app.services.ticker_rename import absorb_duplicate
    keep, dup = "ZZFB1", "ZZFB2"
    try:
        async with ScriptSessionLocal() as s:
            for sym in (keep, dup):
                await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'First-bar test', true)"), {"s": sym})
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2021-07-01', 'sec_fb', 10, 1, 1, 0, now())"), {"s": keep})
            ids = dict((await s.execute(text("SELECT symbol, id FROM tickers WHERE symbol IN (:a, :b)"), {"a": keep, "b": dup})).all())
            await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, created_at) VALUES (gen_random_uuid(), :t, 'fomc', '2019-03-20', 1.0, now())"), {"t": ids[dup]})   # before the first bar
            await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, created_at) VALUES (gen_random_uuid(), :t, 'fomc', '2022-03-16', 1.0, now())"), {"t": ids[dup]})   # after it
            await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, created_at) VALUES (gen_random_uuid(), :t, 'earnings', '2020-01-28', 1.0, now())"), {"t": ids[keep]})  # the kept ticker's own bad row
            await s.commit()
        r = (await run_checks([check_reactions_after_first_bar]))[0]
        assert r.level == ERROR and any(row.startswith(f"{keep} earnings 2020-01-28") for row in r.rows)
        async with ScriptSessionLocal() as s:
            changed = await absorb_duplicate(s, keep, dup)
            await s.commit()
        assert changed["historical_reactions refused (before first bar)"] == 1 and changed["historical_reactions moved"] == 1
        async with ScriptSessionLocal() as s:
            dates = (await s.execute(text("SELECT event_date FROM historical_reactions WHERE ticker_id = :t ORDER BY 1"), {"t": ids[keep]})).scalars().all()
        assert [d.isoformat() for d in dates] == ["2020-01-28", "2022-03-16"]        # the 2019 row never arrived
    finally:
        async with ScriptSessionLocal() as s:
            for sym in (keep, dup):
                await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
                await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
                await s.execute(text("DELETE FROM ticker_aliases WHERE old_symbol = :s OR symbol = :s"), {"s": sym})
                await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


# ── 3. CTVA ──────────────────────────────────────────────────────────────────

def test_rv_snapshots_are_dated_by_their_bars_and_the_trailing_sessions_are_rewritten():
    idx = pd.to_datetime(["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"])
    assert rv.snapshot_dates(idx, 5) == [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
    assert rv.snapshot_dates(idx[:2], 5) == [date(2026, 9, 28), date(2026, 9, 29)]
    assert rv.RECOMPUTE_SESSIONS == 5
    import inspect
    src = inspect.getsource(rv.main)
    assert "for as_of in snapshot_dates(bars.index, RECOMPUTE_SESSIONS)" in src and "await _upsert_snapshot(sym, as_of, metrics)" in src
    assert "sub = bars[bars.index.date <= as_of]" in src                                   # each date from the bars through it, never beyond
    assert "_drop_snapshots_after(sym, metrics[\"last_bar_date\"])" in src                    # a snapshot dated after the newest bar is removed


def _warned(result) -> int:
    """The count a check's message leads with, or 0 on a pass."""
    import re as _re
    m = _re.match(r"(\d+) ", result.message)
    return int(m.group(1)) if m and result.level != PASS else 0


@pytest.mark.asyncio
async def test_validate_warns_when_a_snapshot_repeats_the_previous_days_value():
    """Counted, not listed: the local database can hold hundreds of carried-forward Monday rows from before this fix."""
    sym = "ZZRVS"
    try:
        before = _warned((await run_checks([check_rv_snapshot_unchanged]))[0])
        async with ScriptSessionLocal() as s:
            await s.execute(text("""INSERT INTO rv_snapshots (id, symbol, as_of_date, rv_20d, rv_rank, status, sample_days, created_at)
                                    VALUES (gen_random_uuid(), :s, CURRENT_DATE - 3, 6.433264, 99.9, 'ok', 252, now()), (gen_random_uuid(), :s, CURRENT_DATE - 1, 6.433264, 99.9, 'ok', 252, now())"""), {"s": sym})
            await s.commit()
        r = (await run_checks([check_rv_snapshot_unchanged]))[0]
        assert r.level == WARN and _warned(r) == before + 1
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE rv_snapshots SET rv_20d = 0.415310 WHERE symbol = :s AND as_of_date = CURRENT_DATE - 1"), {"s": sym})
            await s.commit()
        assert _warned((await run_checks([check_rv_snapshot_unchanged]))[0]) == before
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM rv_snapshots WHERE symbol = :s"), {"s": sym})
            await s.commit()
