"""One failing check must not take the checks after it down with it."""
import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.validate_data import ERROR, PASS, CheckResult, run_checks


async def check_that_raises(session) -> CheckResult:
    await session.execute(text("SELECT no_such_column FROM tickers"))   # a real bad query, aborts a Postgres transaction
    return CheckResult("check_that_raises", PASS, "unreachable")


async def check_that_passes(session) -> CheckResult:
    n = (await session.execute(text("SELECT count(*) FROM tickers"))).scalar()
    return CheckResult("check_that_passes", PASS, f"{n} tickers")


def test_a_raising_check_is_recorded_and_the_next_check_still_runs():
    results = asyncio.run(run_checks([check_that_raises, check_that_passes]))
    assert [r.name for r in results] == ["check_that_raises", "check_that_passes"]
    assert results[0].level == ERROR and "Check raised an exception" in results[0].message
    assert results[1].level == PASS, results[1].message          # not "current transaction is aborted"
    assert "aborted" not in results[1].message


def test_each_check_gets_its_own_session():
    opened: list[int] = []

    @asynccontextmanager
    async def counting_factory():
        opened.append(1)
        async with ScriptSessionLocal() as s:
            yield s

    asyncio.run(run_checks([check_that_passes, check_that_raises, check_that_passes], counting_factory))
    assert len(opened) == 3
