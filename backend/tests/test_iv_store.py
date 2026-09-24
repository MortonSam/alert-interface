"""ATM IV is served from the newest non-null row in the window; a null row never hides an older value; absence carries a reason."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.snapshot_iv import null_iv_reason
from app.services.iv_store import IV_WINDOW_DAYS, get_servable_iv, pick_servable
from app.services.options_read_gate import FACT_VALUE_KEYS, format_facts

SYM = "ZZIV"
TODAY = date(2026, 9, 23)


class _Rollback(Exception):
    pass


async def _fixture(s, with_0921: bool = True):
    # production SNPS on 2026-09-23: a 09-23 row with atm_iv NULL, no 09-22 row, 09-21 = 0.468908
    await s.execute(text("""INSERT INTO iv_history (id, symbol, date, atm_iv, atm_iv_reason, realized_vol_20d, created_at)
        VALUES (gen_random_uuid(), :s, :d23, NULL, 'no implied volatility on the ATM strike for expiration 2026-10-16', 0.6523, now())"""),
        {"s": SYM, "d23": date(2026, 9, 23)})
    if with_0921:
        await s.execute(text("""INSERT INTO iv_history (id, symbol, date, atm_iv, realized_vol_20d, created_at)
            VALUES (gen_random_uuid(), :s, :d21, 0.468908, 0.60, now())"""), {"s": SYM, "d21": date(2026, 9, 21)})


@pytest.mark.asyncio
async def test_snps_three_row_fixture_serves_the_0921_value_at_1945z_on_0923():
    async with ScriptSessionLocal() as s:
        with pytest.raises(_Rollback):
            async with s.begin():
                await _fixture(s)
                iv = await get_servable_iv(s, SYM, TODAY)
                assert iv.value == pytest.approx(0.468908) and iv.as_of == "2026-09-21" and iv.reason is None
                # window arithmetic: 09-21 is inside today - 3 = 09-20; on 09-25 it is not
                iv = await get_servable_iv(s, SYM, date(2026, 9, 25))
                assert iv.value is None and iv.reason.startswith(f"No ATM implied volatility in the last {IV_WINDOW_DAYS} days")
                assert "the 2026-09-23 snapshot recorded none: no implied volatility on the ATM strike" in iv.reason
                assert iv.reason.endswith("; last: 46.9% on 2026-09-21")
                raise _Rollback


@pytest.mark.asyncio
async def test_without_any_value_the_reason_names_the_null_snapshot_and_no_last_good():
    async with ScriptSessionLocal() as s:
        with pytest.raises(_Rollback):
            async with s.begin():
                await _fixture(s, with_0921=False)
                iv = await get_servable_iv(s, SYM, TODAY)
                assert iv.value is None and iv.as_of is None
                assert "recorded none: no implied volatility" in iv.reason and "last:" not in iv.reason
                raise _Rollback


def test_pick_servable_is_pure_and_orders_by_date():
    from types import SimpleNamespace as R
    rows = [R(date=date(2026, 9, 23), atm_iv=None, atm_iv_reason="x"), R(date=date(2026, 9, 21), atm_iv=Decimal("0.468908"), atm_iv_reason=None)]
    served, newest = pick_servable(rows, TODAY)
    assert served.date == date(2026, 9, 21) and newest.date == date(2026, 9, 23)
    assert pick_servable(rows, date(2026, 9, 27)) == (None, None)


def test_snapshot_never_writes_a_bare_null():
    assert null_iv_reason(0.47, 900.0, "2026-10-16") is None
    assert null_iv_reason(None, None, "2026-10-16") == "no current price to locate the ATM strike"
    assert null_iv_reason(None, 900.0, "2026-10-16") == "no implied volatility on the ATM strike for expiration 2026-10-16"
    src = Path(__file__).resolve().parents[1].joinpath("app/scripts/snapshot_iv.py").read_text()
    assert "atm_iv_reason    = EXCLUDED.atm_iv_reason" in src and "cleared by backfill cleanup" in src


def test_fact_block_carries_the_iv_reason_into_the_prose():
    assert "atm_iv_reason" in FACT_VALUE_KEYS
    v = {k: None for k in FACT_VALUE_KEYS}
    v["atm_iv_reason"] = "No ATM implied volatility in the last 3 days; last: 46.9% on 2026-09-21"
    assert format_facts("SNPS", "Synopsys", v)["atm_iv"] == "(unavailable: No ATM implied volatility in the last 3 days; last: 46.9% on 2026-09-21)"
    v["atm_iv"] = 0.468908
    assert format_facts("SNPS", "Synopsys", v)["atm_iv"] == "46.9%"


def test_both_readers_go_through_iv_store_and_nothing_resets_atm_iv():
    src = Path(__file__).resolve().parents[1].joinpath("app/routers/tickers.py").read_text()
    assert src.count("await get_servable_iv(db, sym") == 2
    assert "IVHistory.atm_iv.isnot(None)" not in src
    region = src[src.index('@router.get("/options-read/{symbol}"'):src.index("ExplainMetric = ")]
    assert "atm_iv: float | None = None" not in region        # the reset that blanked every read after 3dfa765
    assert '"atm_iv_reason": atm_iv_reason' in region
