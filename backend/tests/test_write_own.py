"""WriteFailures.own (Sam, 2026-10-28): each stock's writes in a transaction of their own. A failure undoes that block alone, is
named, and the next block is written; the step's exit is then a failure. Used by every nightly step that held all its stocks in one
transaction (the calendar refresh, EPS actuals, Release FFO, sector peers, report move history, spin-offs, the macro calendar,
earnings features, recomputed reactions) and by Missed reports and growth."""
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.write_failures import WriteFailures

pytestmark = pytest.mark.xdist_group(name="write_own")
SYMS = ["ZZOWNA", "ZZOWNB"]


async def _cleanup(s):
    await s.execute(text("DELETE FROM tickers WHERE symbol = ANY(:s)"), {"s": SYMS})
    await s.commit()


async def _insert(s, sym):
    await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'own test', false, now(), now())"),
                    {"s": sym})


@pytest.mark.asyncio
async def test_a_failed_block_is_undone_alone_named_and_the_next_is_written():
    writes = WriteFailures("own test")
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        try:
            async with writes.own(s, "ZZOWNA") as a:
                await _insert(s, "ZZOWNA")
            async with writes.own(s, "ZZOWNA again") as dup:
                await _insert(s, "ZZOWNB")                   # written inside the failing block: undone with it
                await _insert(s, "ZZOWNA")                   # the unique symbol: this block fails
            async with writes.own(s, "ZZOWNB") as b:
                await _insert(s, "ZZOWNB")
            assert (a.ok, dup.ok, b.ok) == (True, False, True)
            assert len(writes.rows) == 1 and writes.rows[0].startswith("ZZOWNA again: ") and writes.exit_code() == 1
            async with ScriptSessionLocal() as other:          # committed: another session sees both
                got = (await other.execute(text("SELECT symbol FROM tickers WHERE symbol = ANY(:s) ORDER BY symbol"), {"s": SYMS})).scalars().all()
            assert got == SYMS
        finally:
            await s.rollback()
            await _cleanup(s)
