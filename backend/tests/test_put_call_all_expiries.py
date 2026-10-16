"""Put/call version 4 (2026-10-16): volume summed over every expiration stored for the chain's date, the list kept for the receipt, and
the row's explanation reading the same stored figure (it computed its own from one earnings-picked expiry before)."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.constants import MIN_SIDE_CONTRACTS
from app.database import ScriptSessionLocal
from app.routers.tickers import put_call_for
from app.scripts import compute_put_call as C

pytestmark = pytest.mark.xdist_group(name="put_call_v4")


def _side(*vols):
    return [{"volume": v} for v in vols]


def test_every_expiry_on_or_after_the_chain_date_counts():
    assert C.live_expirations(["2026-10-09", "2026-10-14", "2026-10-16", "2026-11-20"], "2026-10-14") == ["2026-10-14", "2026-10-16", "2026-11-20"]
    assert C.PUT_CALL_COMPUTATION_VERSION == 4


def test_volume_across_expirations_fills_a_ratio_one_weekly_left_thin():
    # VMRK-like: the weekly alone has 29 puts and 5 calls (thin); with the monthly, 79 puts over 55 calls = 1.4364
    weekly = {"puts": _side(20, 9), "calls": _side(5)}
    monthly = {"puts": _side(50), "calls": _side(30, 20)}
    assert C.ratio_from(weekly["calls"], weekly["puts"])[0] is None
    ratio, p, c, used = C.ratio_across([("2026-10-16", weekly), ("2026-11-20", monthly)])
    assert (ratio, p, c, used) == (round(79 / 55, 4), 79, 55, ["2026-10-16", "2026-11-20"])
    assert C.ratio_across([("2026-10-16", weekly)])[0] is None                    # still under MIN_SIDE_CONTRACTS on a side
    assert MIN_SIDE_CONTRACTS == 50


@pytest.mark.asyncio
async def test_the_row_and_its_explanation_read_one_stored_snapshot_with_its_expirations():
    sym, d = "ZZPC", date.today() - timedelta(days=1)
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM put_call_snapshots WHERE symbol = :s"), {"s": sym})
        await s.execute(text("""INSERT INTO put_call_snapshots (id, symbol, snapshot_date, ratio, basis, put_total, call_total, expiration_used,
            expirations_used, computation_version) VALUES (gen_random_uuid(), :s, :d, 1.4364, 'volume', 79, 55, '2026-10-16',
            ARRAY['2026-10-16', '2026-11-20'], 4)"""), {"s": sym, "d": d})
        await s.commit()
    try:
        async with ScriptSessionLocal() as s:
            pc = await put_call_for(s, sym)
        assert pc.ratio == 1.4364 and pc.expirations_used == ["2026-10-16", "2026-11-20"] and pc.expiration_used == "2026-10-16"
        assert (pc.put_total, pc.call_total) == (79, 55)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM put_call_snapshots WHERE symbol = :s"), {"s": sym})
            await s.commit()
