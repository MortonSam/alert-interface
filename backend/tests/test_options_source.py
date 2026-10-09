"""Which chain the pages read (services/options_source): the put-call parity check at 1.0% of the official close, the source order
(courier only by default; Intrinio then the courier with OPTIONS_PRIMARY_SOURCE=intrinio), and the unnamed chain_store readers
following it. Figures from the Oct 5-6, 2026 shadow nights."""
import json
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import chain_store
from app.services import options_source as O

pytestmark = pytest.mark.xdist_group(name="shared_rows")


def chain(call_bid, call_ask, put_bid, put_ask, k=1540.0):
    return {"calls": [{"strike": k, "bid": call_bid, "ask": call_ask}], "puts": [{"strike": k, "bid": put_bid, "ask": put_ask}]}


def test_parity_catches_the_mtd_courier_put_and_passes_intrinios_chain():
    d, exp = date(2026, 10, 6), date(2026, 10, 16)
    courier = O.parity(chain(26.5, 27.0, 372.2, 387.2), 1533.07, d, exp, 0.04, [])      # put mid 379.7: a stale deep in-the-money quote
    intrinio = O.parity(chain(26.5, 27.0, 27.95, 28.45), 1533.07, d, exp, 0.04, [])
    assert not courier.ok and courier.gap_pct < -20 and "break put-call parity by -22.68%" in courier.reason
    assert intrinio.ok and abs(intrinio.gap_pct) < 1.0
    assert O.PARITY_TOLERANCE_PCT == 1.0


def test_parity_tolerance_sits_between_the_timing_cases_and_chtr():
    d, exp = date(2026, 10, 6), date(2026, 10, 9)
    def gap_of(c, p, s, k):
        return O.parity({"calls": [{"strike": k, "bid": c, "ask": c}], "puts": [{"strike": k, "bid": p, "ask": p}]}, s, d, exp, 0.04, [])
    # CHTR Oct 6 Intrinio: call 4.05, put 2.42 at 109 against a 108.64 close -> +1.1% of the close: hidden
    assert not gap_of(4.05, 2.42, 108.64, 109.0).ok
    # a timing-noise chain within 0.87% (FOX, the worst of the 32 consistent cases) passes
    assert gap_of(2.0, 1.9, 55.0, 55.0).ok
    # a dividend going ex before the expiry lowers the forward and is not counted as a parity break
    with_div = O.parity({"calls": [{"strike": 100.0, "bid": 1.0, "ask": 1.0}], "puts": [{"strike": 100.0, "bid": 2.5, "ask": 2.5}]},
                        100.0, d, date(2026, 10, 30), 0.04, [(date(2026, 10, 20), 1.5)])
    assert with_div.ok
    assert O.parity(chain(0, 0, 1, 1), 1533.0, d, date(2026, 10, 16), 0.04, []).reason.startswith("no strike with a quoted call and put")
    assert O.parity(chain(1, 1, 1, 1), None, d, date(2026, 10, 16), 0.04, []).reason == "no official close for the chain's date"


def test_the_source_order_and_the_fallback():
    good = {"chain_date": "2026-10-08", "fresh": True, "ok": True}
    bad = {"chain_date": "2026-10-08", "fresh": True, "ok": False, "reason": "the at-the-money call and put at 110 break put-call parity by -1.67% of the close (limit 1%)"}
    stale = {"chain_date": "2026-10-05", "fresh": False, "ok": True}
    assert O.order("courier") == ["courier"] and O.order("intrinio") == ["intrinio", "courier"]
    assert O.choose("intrinio", {"intrinio": good, "courier": good}).source == "intrinio"
    fb = O.choose("intrinio", {"intrinio": bad, "courier": good})
    assert fb.source == "courier" and fb.reason.startswith("fallback: the Intrinio chain of 2026-10-08 fails the parity check")
    assert O.choose("intrinio", {"intrinio": None, "courier": stale}).reason == "options hidden: no Intrinio chain; the courier chain of 2026-10-05 is stale"
    assert O.choose("courier", {"courier": bad, "intrinio": good}).source is None            # no Intrinio fallback before the switch
    from app.config import Settings
    assert Settings.model_fields["options_primary_source"].default == "courier"


@pytest.mark.asyncio(loop_scope="session")
async def test_unnamed_chain_reads_follow_the_serving_source(monkeypatch):
    from app.config import settings
    sym, d, exp = "ZZOPT", "2026-10-08", "2026-10-16"
    keys = [f"chain:{sym}:{exp}", f"intrinio_chain:{sym}:{exp}", f"chain_parity:{sym}"]
    def mk(src, put):
        return {"calls": [{"strike": 100.0, "bid": 2.0, "ask": 2.2}], "puts": [{"strike": 100.0, "bid": put, "ask": put + 0.2}],
                "expiration": exp, "chain_last_trade": d, "underlying_price": 100.0, "chain_source": src}
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM system_metadata WHERE key = ANY(:k)"), {"k": keys})
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
        await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())"), {"k": keys[0], "v": json.dumps(mk("courier", 30.0))})   # broken put
        await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())"), {"k": keys[1], "v": json.dumps(mk("intrinio", 2.0))})
        await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, close, intrinio_security_id, fetched_at) VALUES (:s, :d, 100.0, 'sec_ZZOPT', now())"), {"s": sym, "d": date.fromisoformat(d)})
        await s.commit()
    O.clear_caches()
    monkeypatch.setattr(chain_store, "is_fresh", lambda *a, **k: True)
    try:
        async with ScriptSessionLocal() as s:
            monkeypatch.setattr(settings, "options_primary_source", "courier")
            assert await chain_store.get_chain(s, sym, exp) is None                         # the courier's chain fails: hidden
            note = await O.no_options_note(s, sym)
            assert note.startswith("Options figures are hidden for this ticker: the courier chain of 2026-10-08 fails the parity check")
            monkeypatch.setattr(settings, "options_primary_source", "intrinio")
            got = await chain_store.get_chain(s, sym, exp)
            assert got and got[0]["chain_source"] == "intrinio"
            assert await chain_store.get_latest_chain_date(s, sym) == d and await chain_store.pick_expiration(s, sym, d) == exp
            assert (await chain_store.get_chain(s, sym, exp, source="courier"))[0]["chain_source"] == "courier"     # a named source is read as named
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM system_metadata WHERE key = ANY(:k)"), {"k": keys})
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.commit()
        O.clear_caches()
