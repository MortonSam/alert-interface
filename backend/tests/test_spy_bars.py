"""SPY's bars keep coming after the nightly bars step went active-only (2026-10-12): SPY has no ticker row, so the active filter
dropped it and the session calendar stopped at 2026-10-09 while the index names had 2026-10-12. validate spy_bar_current catches it."""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import shadow_price_bars
from app.scripts.validate_data import CHECKS, check_spy_bar_current, benchmark_lag

SRC = Path(shadow_price_bars.__file__).read_text()


@pytest.mark.asyncio
async def test_the_bars_plan_holds_spy_and_no_inactive_ticker():
    _, ids = await shadow_price_bars.load_plan(date.today())
    planned = {sym for sym, _ in ids}
    async with ScriptSessionLocal() as s:
        has_spy_record = bool(await s.scalar(text("SELECT count(*) FROM security_records WHERE symbol = 'SPY'")))
        inactive = set((await s.execute(text("SELECT symbol FROM tickers WHERE NOT is_active"))).scalars().all())
    assert has_spy_record and "SPY" in planned
    assert not (planned & inactive)
    _, only = await shadow_price_bars.load_plan(date.today(), only={"SPY"})
    assert {sym for sym, _ in only} == {"SPY"}


@pytest.mark.asyncio
async def test_the_plan_runs_in_a_read_only_transaction_and_names_spy(capsys):
    assert await shadow_price_bars.main(["--plan", "--symbols=SPY"]) == 0
    out = capsys.readouterr().out
    assert "symbol(s)" in out and all(line.split()[0] == "SPY" for line in out.splitlines() if line.startswith("  "))


def test_the_plan_reads_read_only_and_a_backfill_leaves_the_nightly_outcome():
    assert "or_(SecurityRecord.symbol.in_(active), SecurityRecord.symbol.in_(BENCHMARKS))" in SRC
    assert "load_plan(today, read_only_factory(settings.database_url), only)" in SRC
    assert "if not only:            # a --symbols backfill is not the nightly step" in SRC


def test_benchmark_lag_names_spy_behind_the_index():
    d9, d12 = date(2026, 10, 9), date(2026, 10, 12)
    assert benchmark_lag(d9, [d12] * 503 + [d9] * 9) == "SPY's last bar is 2026-10-09; 503 of 512 index names last have a bar on 2026-10-12"
    assert benchmark_lag(d12, [d12] * 503 + [d9] * 9) is None
    assert benchmark_lag(None, [d12, d12]).startswith("no SPY bar stored")
    assert benchmark_lag(d12, []) is None


@pytest.mark.asyncio
async def test_spy_bar_current_is_a_validate_check_and_runs():
    assert check_spy_bar_current in CHECKS
    async with ScriptSessionLocal() as s:
        r = await check_spy_bar_current(s)
    assert r.name == "spy_bar_current" and r.message
