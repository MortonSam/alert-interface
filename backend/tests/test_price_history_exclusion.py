"""One exclusion list, shared: the RV guard's data_error verdict removes a ticker
from every reaction pipeline, and validate fails while any of its rows remain.

Runs against the local database inside a rolled-back transaction.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal, script_engine
from app.scripts.validate_data import ERROR, PASS, check_excluded_ticker_has_no_reactions
from app.services.price_history_exclusion import apply_exclusion, clear_excluded, excluded_symbols

SYM = "ZZEXCL"


async def _setup(session) -> str:
    ticker_id = await session.scalar(text("""
        INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at)
        VALUES (gen_random_uuid(), :s, 'Exclusion test', true, now(), now()) RETURNING id
    """), {"s": SYM})
    await session.execute(text("""
        INSERT INTO rv_snapshots (id, symbol, as_of_date, sample_days, status, created_at)
        VALUES (gen_random_uuid(), :s, :d1, 0, 'ok', now()),
               (gen_random_uuid(), :s, :d2, 0, 'data_error', now())
    """), {"s": SYM, "d1": date(2026, 9, 18), "d2": date(2026, 9, 21)})
    await session.execute(text("""
        INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, computation_version, created_at)
        VALUES (gen_random_uuid(), :t, 'earnings', :d, :p, 3, now()),
               (gen_random_uuid(), :t, 'analyst_action', :d, :p, 2, now())
    """), {"t": ticker_id, "d": date(2026, 6, 1), "p": Decimal("-35.84")})
    await session.execute(text("""
        INSERT INTO analyst_reaction_stats (id, symbol, upgrade_count, upgrade_5d_sample, downgrade_count, downgrade_5d_sample, computed_at)
        VALUES (gen_random_uuid(), :s, 0, 0, 3, 3, now())
    """), {"s": SYM})
    return ticker_id


def _run(coro):
    """Each test gets its own event loop; the pooled connections must not outlive it."""
    async def wrapped():
        try:
            return await coro
        finally:
            await script_engine.dispose()

    return asyncio.run(wrapped())


def test_latest_snapshot_status_decides_the_list_and_clearing_empties_every_table():
    async def body():
        async with ScriptSessionLocal() as session:
            async with session.begin():
                await _setup(session)
                assert SYM in await excluded_symbols(session)

                # rows exist -> validate ERROR naming each table
                out = await check_excluded_ticker_has_no_reactions(session)
                assert out.level == ERROR
                assert any(f"{SYM}: 1 earnings reaction row(s)" == r for r in out.rows)
                assert any(f"{SYM}: 1 analyst_action reaction row(s)" == r for r in out.rows)
                assert any(f"{SYM}: analyst_reaction_stats row" == r for r in out.rows)

                counts = await clear_excluded(session, {SYM})
                assert counts == {"reactions": 2, "stats": 1}
                out = await check_excluded_ticker_has_no_reactions(session)
                assert out.level == PASS and SYM in out.message

                # A newer ok snapshot takes the ticker off the list
                await session.execute(text("""
                    INSERT INTO rv_snapshots (id, symbol, as_of_date, sample_days, status, created_at)
                    VALUES (gen_random_uuid(), :s, :d, 0, 'ok', now())
                """), {"s": SYM, "d": date(2026, 9, 22)})
                assert SYM not in await excluded_symbols(session)
                raise _Rollback

    with pytest.raises(_Rollback):
        _run(body())


def test_apply_exclusion_reports_and_commits_nothing_when_list_is_empty(capsys):
    async def body():
        async with ScriptSessionLocal() as session:
            async with session.begin():
                before = await excluded_symbols(session)
                if before:
                    pytest.skip("local database has excluded tickers; the empty-list branch is not testable here")
                assert await apply_exclusion(session, "Test step") == set()
                raise _Rollback

    with pytest.raises(_Rollback):
        _run(body())
    assert "skipping" not in capsys.readouterr().out


class _Rollback(Exception):
    """Raised to roll the test transaction back."""
