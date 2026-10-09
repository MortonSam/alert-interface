"""build_security_records: a moved first-price date for the same Intrinio security moves the current record's start; it never adds
a second current record (BKR, 2026-10-09: sec_gN27dE's first_stock_price went from 1987-04-07 to 2013-10-14 and a duplicate
current row appeared). A different security under the ticker is still a new record."""
from datetime import date

import pytest
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.security_record import SecurityRecord
from app.scripts.build_security_records import upsert
from app.services.security_records import CURRENT, INTRINIO, Record

pytestmark = pytest.mark.xdist_group(name="shared_rows")
SYM = "ZZREC"


@pytest.mark.asyncio(loop_scope="session")
async def test_a_moved_first_price_date_moves_the_start_and_adds_no_row():
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": SYM})
        await s.commit()
    try:
        async with ScriptSessionLocal() as s:
            await upsert(s, [Record(SYM, "sec_A", "FIGI1", "C1", "Co", date(1987, 4, 7), None, CURRENT, INTRINIO)], {})
            await s.commit()
        async with ScriptSessionLocal() as s:
            ins, upd, _ = await upsert(s, [Record(SYM, "sec_A", "FIGI1", "C1", "Co", date(2013, 10, 14), None, CURRENT, INTRINIO)], {})
            await s.commit()
            rows = (await s.execute(select(SecurityRecord).where(SecurityRecord.symbol == SYM))).scalars().all()
        assert (ins, upd) == (0, 1) and [(r.valid_from, r.role) for r in rows] == [(date(2013, 10, 14), CURRENT)]
        async with ScriptSessionLocal() as s:          # another security under the ticker is a new row (the FIGI check reports it)
            ins, _, _ = await upsert(s, [Record(SYM, "sec_B", "FIGI2", "C2", "Co", date(2026, 1, 2), None, CURRENT, INTRINIO)], {})
            await s.commit()
        assert ins == 1
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": SYM})
            await s.commit()
