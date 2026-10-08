"""Three Discover fixes: void picks on no public surface, one session dominating the realized window, the RV rank held after a
corporate action."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import briefing_build as BB
from app.services.discover_blurbs import volatility_blurb
from app.services.rv_hold import CLEAN_SESSIONS_NEEDED, hold_reason, rank_holds, sessions_cutoff
from app.services.rv_math import DOMINANT_SHARE, compute_rv_metrics, dominant_session


def test_one_session_over_half_the_variance_is_named_and_the_comparison_is_withheld():
    idx = pd.bdate_range("2026-09-01", periods=60)
    closes = pd.Series(100.0 + np.linspace(0, 3, 60), index=idx)
    closes.iloc[-2] *= 1.335                                     # PTC's shape: +33.5% on one session
    closes.iloc[-1] = closes.iloc[-2] * 1.004
    lr = np.log(closes / closes.shift(1)).dropna()
    dom = dominant_session(lr)
    assert dom["date"] == idx[-2].date() and abs(dom["move_pct"] - 33.5) < 0.2 and dom["share"] > DOMINANT_SHARE
    quiet = dominant_session(pd.Series(np.random.default_rng(1).normal(0, 0.01, 60), index=idx))
    assert quiet is not None and quiet["share"] < DOMINANT_SHARE
    m = compute_rv_metrics(pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.01, 400))), index=pd.bdate_range("2025-01-01", periods=400)))
    assert m["status"] == "ok" and {"dominant_date", "dominant_move_pct", "dominant_share"} <= set(m)
    assert volatility_blurb(-99.0, "iv_cheap", 96.8, "one session dominates the 20-day window: Oct 5, 2026 (+33.5%)") == "one session dominates the 20-day window: Oct 5, 2026 (+33.5%) · RV rank 97, extreme"
    assert volatility_blurb(12.0, "iv_rich", 92.0) == "IV rich at +12pp vs realized · RV rank 92, extreme"


def test_the_rank_hold_names_the_action_and_counts_sessions():
    assert hold_reason("spin_off", "Vylor", date(2026, 10, 1)) == f"Spun off Vylor on Oct 1, 2026; {CLEAN_SESSIONS_NEEDED} clean sessions after it are needed"
    assert hold_reason("rename_merge", "EQR", date(2026, 10, 5)).startswith("Renamed from EQR on Oct 5, 2026 after a merger")
    cutoff = sessions_cutoff(date(2026, 10, 7))
    assert date(2025, 10, 1) <= cutoff <= date(2025, 10, 10)                 # 252 sessions is about a year


@pytest.mark.asyncio
async def test_a_recorded_spin_off_holds_the_rank_on_the_strip_discover_and_ask_ivy_and_a_void_pick_is_off_discover(monkeypatch):
    sym = "ZZSPUN"
    today = date.today()
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, sector) VALUES (gen_random_uuid(), :s, 'Spun Test, Inc.', true, 'Industrials')"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                    VALUES (gen_random_uuid(), :t, 'other', :d, 'x', 'edgar', true, '{"corporate_action": "spin_off", "counterparty": "Vylor"}', now(), now())"""),
                            {"t": tid, "d": today - timedelta(days=30)})
            await s.execute(text("""INSERT INTO rv_snapshots (id, symbol, as_of_date, rv_20d, rv_rank, rv_percentile, rv_min_1y, rv_max_1y, sample_days, status, last_bar_date, created_at)
                                    VALUES (gen_random_uuid(), :s, :d, 0.58, 100.0, 100.0, 0.2, 0.58, 252, 'ok', :d, now())"""), {"s": sym, "d": today - timedelta(days=1)})
            # a void pick, the newest of all, which Discover's ledger strip must skip
            await s.execute(text("""INSERT INTO alert_picks (id, symbol, picked_direction, leans, entry_price, generated_at, status, algo_version, source, season, void_reason, voided_at)
                                    VALUES (gen_random_uuid(), :s, 'bullish', '[]', 100, now(), 'void', 'v2.0', 'nightly', 2, 'Report came 17 sessions after entry', now())"""), {"s": sym})
            await s.commit()
        async with ScriptSessionLocal() as db:
            holds = await rank_holds(db, [sym, "MU"], today)
            qs = await BB.build_questions(db, sym, today, all_candidates=True)
            raw: dict = {}
            await BB.build_questions(db, sym, today, raw=raw, all_candidates=True)
        assert holds[sym].startswith("Spun off Vylor on") and "MU" not in holds
        assert "volatile_now" not in [q["key"] for q in qs["questions"]] and "rv" not in raw and raw.get("rv_hold") == holds[sym]
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        import app.routers.discover as D
        monkeypatch.setattr(D, "LEDGER_PUBLIC", True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            tape = (await c.get("/api/v1/discover/unusually-active?limit=50")).json()
            latest = (await c.get("/api/v1/discover/latest-pick")).json()
        assert sym not in [i["symbol"] for i in tape["items"]]                          # rank 100 held: not on the tape
        assert not latest["pick"] or latest["pick"]["symbol"] != sym                    # the void pick is never the ledger strip's pick
        if latest["pick"]:
            assert latest["pick"]["status"] != "void"
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM alert_picks WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM rv_snapshots WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()

# shares alert_picks rows with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="picks")
