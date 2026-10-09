"""Which chain the pages read (services/options_source): the put-call parity check at 0.5% of the official close, the source order
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


def test_the_american_band_fails_the_mtd_courier_chain_and_passes_intrinios_quotes():
    d, exp = date(2026, 10, 6), date(2026, 10, 16)
    # the courier's Oct 6 quotes were not kept; at its stored mids (call 26.75, put 379.70) the pair sits 22.6% under the floor
    courier = O.parity(chain(26.75, 26.75, 379.7, 379.7), 1533.07, d, exp, 0.04, [])
    assert not courier.ok and courier.gap_pct > 20 and "below the floor" in courier.reason
    # Intrinio's re-fetched Oct 6 EOD quotes: call 20.00/33.50, put 22.50/33.90 at 1540 -> inside the band
    intrinio = O.parity(chain(20.0, 33.5, 22.5, 33.9), 1533.07, d, exp, 0.04, [])
    assert intrinio.ok and intrinio.gap_pct == 0.0
    assert intrinio.detail["ca_minus_pb"] == 11.0 and intrinio.detail["cb_minus_pa"] == -13.9


def test_chtr_oct_6_intrinio_quotes_sit_inside_the_band_and_the_band_is_judged_from_the_quotes():
    d, exp = date(2026, 10, 6), date(2026, 10, 9)
    chtr = O.parity(chain(1.40, 6.20, 1.15, 4.70, k=109.0), 108.64, d, exp, 0.04, [])
    assert chtr.ok and chtr.detail["floor"] == -0.36                    # call ask - put bid 5.05 >= floor; call bid - put ask -3.30 <= ceiling
    # the same mids with a tight market would sit outside: the quotes, not the mid, decide
    tight = O.parity(chain(3.79, 3.81, 2.92, 2.93, k=109.0), 108.64, d, exp, 0.04, [], tolerance_pct=0.5)
    assert not tight.ok and "above the ceiling" in tight.reason
    # a dividend going ex before the expiry lowers the floor
    div = O.parity(chain(1.0, 1.1, 2.4, 2.6, k=100.0), 100.0, d, date(2026, 10, 30), 0.04, [(date(2026, 10, 20), 1.5)])
    assert div.ok
    assert O.parity(chain(1, 0, 1, 1), 1533.0, d, exp, 0.04, []).reason.startswith("no strike with a quoted call and put")
    assert O.parity(chain(1, 1, 1, 1), None, d, exp, 0.04, []).reason == "no official close for the chain's date"


def test_the_source_order_the_fallback_and_hidden_by_check():
    good = {"chain_date": "2026-10-08", "fresh": True, "ok": True}
    bad = {"chain_date": "2026-10-08", "fresh": True, "ok": False, "reason": "outside the band"}
    stale = {"chain_date": "2026-10-05", "fresh": False, "ok": True}
    assert O.order("courier") == ["courier"] and O.order("intrinio") == ["intrinio", "courier"]
    assert O.choose("intrinio", {"intrinio": good, "courier": good}).source == "intrinio"
    fb = O.choose("intrinio", {"intrinio": bad, "courier": good})
    assert fb.source == "courier" and fb.reason.startswith("fallback: the Intrinio chain of 2026-10-08 fails the put-call band check")
    gone = O.choose("intrinio", {"intrinio": None, "courier": stale})
    assert gone.source is None and gone.hidden_by_check is False                       # missing or stale is not a failed check
    assert O.choose("intrinio", {"intrinio": bad, "courier": stale}).hidden_by_check is True
    assert O.choose("courier", {"courier": bad, "intrinio": good}).source is None       # no Intrinio fallback in courier mode


def test_the_visitor_sentence_is_exact_and_names_no_vendor_check_or_percentage():
    assert O.PAUSED_NOTE == ("Options figures for this stock are paused until the next update. The latest options quotes didn't line up "
                             "with the stock's closing price, so we're holding them back.")
    low = O.PAUSED_NOTE.lower()
    for word in ("intrinio", "courier", "parity", "%", "band"):
        assert word not in low
    from pathlib import Path
    root = Path(O.__file__).resolve().parents[1]
    for f in ("services/iv_store.py", "routers/discover.py", "services/options_source.py"):
        assert '"parity" in' not in (root / f).read_text()


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
        await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())"), {"k": keys[0], "v": json.dumps(mk("courier", 30.0))})   # a put far outside the band
        await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())"), {"k": keys[1], "v": json.dumps(mk("intrinio", 2.0))})
        await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, close, intrinio_security_id, fetched_at) VALUES (:s, :d, 100.0, 'sec_ZZOPT', now())"), {"s": sym, "d": date.fromisoformat(d)})
        await s.commit()
    O.clear_caches()
    monkeypatch.setattr(chain_store, "is_fresh", lambda *a, **k: True)
    try:
        async with ScriptSessionLocal() as s:
            monkeypatch.setattr(settings, "options_primary_source", "courier")
            assert await chain_store.get_chain(s, sym, exp) is None                         # the courier's chain fails: hidden
            assert await O.no_options_note(s, sym) == O.PAUSED_NOTE
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
