"""validate's rv_snapshot_coverage: an active ticker with no RV snapshot on the newest snapshot date is an ERROR naming it.
2026-10-08: CTVA had no Oct 7 row and left the tape without a word (it had been deactivated as an S&P 500 leaver that night;
an inactive ticker is not counted, an active one with no row is)."""
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import validate_data as V

pytestmark = pytest.mark.xdist_group(name="shared_rows")     # reads every active ticker's snapshot


def test_the_line_names_every_missing_ticker():
    assert V.missing_snapshot_line(date(2026, 10, 7), ["CTVA", "ZZA"]) == (
        "2 active ticker(s) have no RV snapshot for 2026-10-07, so they leave the tape and the strip silently: CTVA, ZZA")
    assert V.check_rv_snapshot_coverage in V.CHECKS


@pytest.mark.asyncio(loop_scope="session")
async def test_an_active_ticker_without_a_row_on_the_newest_date_errors_and_an_inactive_one_does_not():
    sym = "ZZRVCOV"
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM rv_snapshots WHERE symbol = :s"), {"s": sym})
        await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'Coverage test', true, now(), now())"), {"s": sym})
        await s.commit()
        try:
            r = await V.check_rv_snapshot_coverage(s)
            if r.level != V.WARN:                     # an empty table has no newest date
                assert r.level == V.ERROR and sym in r.message
            await s.execute(text("UPDATE tickers SET is_active = false WHERE symbol = :s"), {"s": sym})
            await s.commit()
            r = await V.check_rv_snapshot_coverage(s)
            assert sym not in r.message
        finally:
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
