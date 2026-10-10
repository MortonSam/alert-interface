"""A day's printed move is its close against the previous close as traded, everywhere: on an ex-dividend day the dividend-adjusted
return differs (AT&T, Oct 9, 2026: -9.81% adjusted, -10.82% as traded, a $0.2775 dividend). The unusually-active dominant move and
the stored-close quote both print the as-traded figure, the one Discover's movers and the live quote print."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import quote_fallback, rv_store

SYM = "ZZTX"
BARS = [("2026-10-07", 24.47, 1.0), ("2026-10-08", 24.87, 1.0), ("2026-10-09", 22.18, 0.988841978287093)]   # AT&T's stored bars


async def _seed(dominant_date="2026-10-09"):
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": SYM})
        await s.execute(text("DELETE FROM rv_snapshots WHERE symbol = :s"), {"s": SYM})
        for d, c, f in BARS:
            await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, open, high, low, close, volume, factor, split_ratio, dividend, fetched_at)
                                    VALUES (:s, :d, 'sec_zztx', :c, :c, :c, :c, 1000, :f, 1, 0, now())"""), {"s": SYM, "d": date.fromisoformat(d), "c": c, "f": f})
        await s.execute(text("""INSERT INTO rv_snapshots (id, symbol, as_of_date, rv_20d, rv_rank, rv_percentile, rv_min_1y, rv_max_1y, sample_days, status,
                                    last_bar_date, last_bar_close, created_at, dominant_date, dominant_move_pct, dominant_share)
                                VALUES (gen_random_uuid(), :s, '2026-10-09', 0.41, 100, 100, 0.1, 0.41, 250, 'ok', '2026-10-09', 22.18, now(), :dd, -9.81, 0.62)"""),
                        {"s": SYM, "dd": date.fromisoformat(dominant_date)})
        await s.commit()


async def _drop():
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": SYM})
        await s.execute(text("DELETE FROM rv_snapshots WHERE symbol = :s"), {"s": SYM})
        await s.commit()


@pytest.mark.asyncio
async def test_the_dominant_move_prints_as_traded_not_dividend_adjusted():
    await _seed()
    try:
        async with ScriptSessionLocal() as s:
            row = (await rv_store.get_latest_rv_bulk(s, [SYM]))[SYM]
        assert float(row.dominant_move_pct) == -10.82 and float(row.dominant_move_adjusted_pct) == -9.81
        assert rv_store.dominant_note(row) == "one session dominates the 20-day window: Oct 9, 2026 (-10.8%)"
    finally:
        await _drop()


@pytest.mark.asyncio
async def test_without_both_closes_the_dominant_move_is_absent_never_the_adjusted_figure():
    await _seed(dominant_date="2026-10-07")             # no stored close before Oct 7
    try:
        async with ScriptSessionLocal() as s:
            row = (await rv_store.get_latest_rv_bulk(s, [SYM]))[SYM]
        assert row.dominant_move_pct is None
        assert rv_store.dominant_note(row) == "one session dominates the 20-day window: Oct 7, 2026"
    finally:
        await _drop()


@pytest.mark.asyncio
async def test_the_stored_close_quote_changes_against_the_previous_close_as_traded():
    await _seed()
    try:
        q = quote_fallback.stored_close_quote_sync(SYM, today=date(2026, 10, 10))
        assert (q["c"], q["pc"], round(q["dp"], 2)) == (22.18, 24.87, -10.82)
    finally:
        await _drop()
