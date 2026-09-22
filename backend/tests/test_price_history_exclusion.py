"""The price-history exclusion hides at read time and never deletes.

An excluded ticker's reaction and stats rows stay in their tables through the
earnings seeder and the analyst-stats step, every API reader returns nothing
for it and states the reason, and the validate check reports the rows as
hidden. Runs on the session-wide loop (see conftest); the survival test
commits a synthetic ticker and removes it afterwards, because the pipelines
open their own sessions.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.main import app
from app.scripts import compute_analyst_reactions, seed_historical_reactions
from app.scripts.validate_data import ERROR, PASS, check_excluded_ticker_hidden
from app.services.price_history_exclusion import EXCLUSION_REASON, excluded_symbols, exclusion_list

SYM = "ZZEXCL"


async def _create(session) -> str:
    tid = await session.scalar(text("""
        INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at)
        VALUES (gen_random_uuid(), :s, 'Exclusion test', true, now(), now()) RETURNING id
    """), {"s": SYM})
    await session.execute(text("""
        INSERT INTO rv_snapshots (id, symbol, as_of_date, sample_days, status, created_at)
        VALUES (gen_random_uuid(), :s, :d1, 0, 'ok', now()), (gen_random_uuid(), :s, :d2, 0, 'data_error', now())
    """), {"s": SYM, "d1": date(2026, 9, 18), "d2": date(2026, 9, 21)})
    await session.execute(text("""
        INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, eps_estimate, eps_actual, outcome, computation_version, created_at)
        VALUES (gen_random_uuid(), :t, 'earnings', :d, :p, 1.0, 1.1, 'beat', 3, now()),
               (gen_random_uuid(), :t, 'analyst_action', :d, :p, NULL, NULL, 'unknown', 2, now())
    """), {"t": tid, "d": date(2026, 6, 1), "p": Decimal("-35.84")})
    await session.execute(text("""
        INSERT INTO analyst_reaction_stats (id, symbol, upgrade_count, upgrade_5d_sample, downgrade_count, downgrade_5d_sample, computed_at)
        VALUES (gen_random_uuid(), :s, 0, 0, 3, 3, now())
    """), {"s": SYM})
    return tid


async def _counts(session, tid) -> tuple[int, int]:
    reactions = await session.scalar(text("SELECT count(*) FROM historical_reactions WHERE ticker_id = :t"), {"t": tid})
    stats = await session.scalar(text("SELECT count(*) FROM analyst_reaction_stats WHERE symbol = :s"), {"s": SYM})
    return reactions, stats


async def _remove(session):
    await session.execute(text("DELETE FROM analyst_reaction_stats WHERE symbol = :s"), {"s": SYM})
    await session.execute(text("DELETE FROM rv_snapshots WHERE symbol = :s"), {"s": SYM})
    await session.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})   # cascades reactions
    await session.commit()


@pytest.mark.asyncio
async def test_excluded_ticker_rows_survive_the_seeder_and_the_analyst_step_and_readers_say_why(monkeypatch, capsys):
    async with ScriptSessionLocal() as session:
        await _remove(session)
        tid = await _create(session)
        await session.commit()
    try:
        async with ScriptSessionLocal() as session:
            assert SYM in await excluded_symbols(session)
            assert await _counts(session, tid) == (2, 1)

        # the earnings seeder, forced over every ticker, with the per-ticker work stubbed (no yfinance)
        async def no_work(ticker, loop): return True, 0, 0, 0
        monkeypatch.setattr(seed_historical_reactions, "process_ticker_bulk", no_work)
        monkeypatch.setattr(seed_historical_reactions, "BULK_BATCH_SLEEP", 0)      # one pass, no pacing
        monkeypatch.setattr(seed_historical_reactions, "BULK_BATCH_SIZE", 10_000)
        monkeypatch.setattr(seed_historical_reactions, "save_failed_reactions", lambda syms: None)
        monkeypatch.setattr(seed_historical_reactions, "load_failed_reactions", lambda: [])
        await seed_historical_reactions.main_bulk(retry_only=False, limit=None, force=True)

        # the analyst-stats step, with the per-ticker work stubbed
        async def no_analyst(ticker, loop): return True, 0
        monkeypatch.setattr(compute_analyst_reactions, "_process_ticker_with_retries", no_analyst)
        monkeypatch.setattr(compute_analyst_reactions, "BATCH_SLEEP", 0)
        monkeypatch.setattr("sys.argv", ["compute_analyst_reactions", "--limit", "3"])
        await compute_analyst_reactions.main()

        out = capsys.readouterr().out
        assert "skipping" in out and SYM in out and "hidden at read time" in out

        async with ScriptSessionLocal() as session:
            assert await _counts(session, tid) == (2, 1)          # nothing deleted
            check = await check_excluded_ticker_hidden(session)
            assert check.level == PASS and any(f"{SYM}: 2 reaction row(s) and 1 stats row(s) stored" in r for r in check.rows)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            summary = (await client.get(f"/api/v1/reactions/summary?symbol={SYM}")).json()
            assert summary["total_quarters"] == 0 and summary["price_history_excluded"] is True
            assert summary["exclusion_reason"] == EXCLUSION_REASON
            cond = (await client.get(f"/api/v1/reactions/conditional?symbol={SYM}")).json()
            assert cond["total_quarters"] == 0 and cond["exclusion_reason"] == EXCLUSION_REASON
            stats = (await client.get(f"/api/v1/reactions/analyst-stats?symbol={SYM}")).json()
            assert stats["downgrade_count"] == 0 and stats["exclusion_reason"] == EXCLUSION_REASON
            assert (await client.get(f"/api/v1/reactions?symbol={SYM}")).json() == []
    finally:
        async with ScriptSessionLocal() as session:
            await _remove(session)


@pytest.mark.asyncio
async def test_validate_flags_a_stored_derivation_that_still_carries_an_excluded_ticker():
    class _Rollback(Exception):
        pass
    async def body():
        async with ScriptSessionLocal() as s:
            async with s.begin():
                tid = await _create(s)
                await s.execute(text("""INSERT INTO magnitude_trend_snapshots (id, symbol, as_of_date, trend, created_at)
                    VALUES (gen_random_uuid(), :s, :d, 'stable', now())"""), {"s": SYM, "d": date(2026, 9, 21)})
                out = await check_excluded_ticker_hidden(s)
                assert out.level == ERROR and any(f"{SYM}: 1 row(s) in magnitude_trend_snapshots" == r for r in out.rows)
                raise _Rollback
    with pytest.raises(_Rollback):
        await body()


def test_nothing_deletes_on_an_exclusion_verdict():
    root = Path(__file__).resolve().parents[1].joinpath("app")
    svc = root.joinpath("services/price_history_exclusion.py").read_text()
    assert "delete(" not in svc and "DELETE" not in svc and "clear_excluded" not in svc
    for script in ("scripts/seed_historical_reactions.py", "scripts/compute_analyst_reactions.py", "scripts/seed_fomc_reactions.py"):
        src = root.joinpath(script).read_text()
        assert "apply_exclusion" not in src and "clear_excluded" not in src
