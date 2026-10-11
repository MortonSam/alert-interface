"""One filter for every stored chain (services/chain_quality, applied by chain_store.put_chain): adjusted roots, impossible quotes and
duplicate strikes never reach a reader, and validate's chain_quality check names any stored chain that still holds one."""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.validate_data import CHECKS, ERROR, check_chain_quality
from app.services import chain_store
from app.services.chain_quality import MAX_SANE_IV, adjusted_root, clean_chain, problems
from app.services.chain_shadow import to_stored_chain

pytestmark = pytest.mark.xdist_group(name="chain_quality")


def q(strike, bid, ask, oi=0, iv=0.5, root=None, last=None):
    c = {"strike": strike, "bid": bid, "ask": ask, "lastPrice": last, "openInterest": oi, "volume": 0, "impliedVolatility": iv}
    if root:
        c["root"] = root
    return c


def test_an_adjusted_root_is_dropped_even_with_more_open_interest():
    # BDX on 2026-10-09: the adjusted BDX1 $185 call (bid 56) held more open interest than the standard one (bid 7.90)
    chain = {"underlying_price": 183.75, "intrinio_ticker": "BDX", "chain_source": "intrinio",
             "calls": [q(185, 7.9, 9.3, oi=23, iv=0.278, root="BDX"), q(185, 56.0, 60.5, oi=29, iv=1.88, root="BDX1")],
             "puts": [q(185, 8.2, 10.7, oi=32, root="BDX"), q(185, 0.10, 4.9, oi=61, root="BDX1")]}
    out = clean_chain(chain, "BDX")
    assert [c["bid"] for c in out["calls"]] == [7.9] and [c["bid"] for c in out["puts"]] == [8.2]
    assert out["chain_quality"] == {"dropped_nonstandard": 2, "dropped_duplicates": 0}
    assert problems(chain, "BDX")["root"] == 2 and problems(out, "BDX") == {"root": 0, "iv": 0, "price": 0, "duplicate": 0}
    assert adjusted_root("HON2", "HON") and adjusted_root("BRKB1", "BRK.B") and not adjusted_root("HON", "HON") and not adjusted_root("GOOG", "GOOGL")


def test_impossible_quotes_are_dropped_and_a_deep_put_is_not():
    chain = {"underlying_price": 100.0, "chain_source": "courier",
             "calls": [q(360, 609.0, 612.0), q(100, 4.0, 4.4, iv=MAX_SANE_IV + 1), q(105, 1.0, 1.2), q(20, None, None, last=100.0)],
             "puts": [q(250, 149.0, 151.0), q(90, 95.0, 96.0)]}     # a $250 put at $150 is real; a $90 put at $95.50 is not
    out = clean_chain(chain, "ZZQ")
    assert [c["strike"] for c in out["calls"]] == [105] and [c["strike"] for c in out["puts"]] == [250]
    assert problems(chain, "ZZQ") == {"root": 0, "iv": 1, "price": 3, "duplicate": 0}


def test_a_strike_listed_twice_without_roots_keeps_the_most_open_interest():
    chain = {"underlying_price": 418.78, "chain_source": "courier",
             "calls": [q(420, 38.75, 41.10, oi=601), q(420, 30.0, 33.0, oi=2)], "puts": []}
    out = clean_chain(chain, "PANW")
    assert [(c["strike"], c["openInterest"]) for c in out["calls"]] == [(420, 601)] and out["chain_quality"]["dropped_duplicates"] == 1
    assert problems(chain, "PANW")["duplicate"] == 1


def test_intrinio_chains_keep_the_contract_root():
    raw = [{"option": {"strike": 420, "type": "call", "ticker": "PANW1"}, "prices": {"close_bid": 547.8, "close_ask": 552.0, "date": "2026-10-09"}}]
    chain = to_stored_chain(raw, "2026-12-18", date(2026, 10, 9), 418.78, "price_bars_shadow", {"intrinio_ticker": "PANW"},
                            datetime.now(timezone.utc), date(2026, 10, 9))
    assert chain["calls"][0]["root"] == "PANW1" and clean_chain(chain, "PANW")["calls"] == []


@pytest.mark.asyncio
async def test_put_chain_stores_the_cleaned_chain_and_validate_names_a_dirty_one():
    assert check_chain_quality in CHECKS
    sym, exp = "0ZCQ1", "2026-12-18"
    dirty = {"underlying_price": 100.0, "chain_source": "courier", "chain_last_trade": "2026-10-09", "expiration": exp,
             "calls": [q(100, 4.0, 4.4, oi=10), q(100, 3.0, 3.4, oi=1), q(50, 120.0, 121.0)], "puts": []}
    async with ScriptSessionLocal() as s:
        try:
            stored = await chain_store.put_chain(s, sym, exp, dirty, chain_store.COURIER)
            await s.commit()
            got, _ = await chain_store.get_chain(s, sym, exp, source=chain_store.COURIER)
            assert got == stored and [c["openInterest"] for c in got["calls"]] == [10]
            assert got["chain_quality"] == {"dropped_nonstandard": 1, "dropped_duplicates": 1}
            assert not any(r.startswith(f"chain:{sym}:") for r in (await check_chain_quality(s)).rows)
            # a chain written around put_chain is reported
            await s.execute(text("UPDATE system_metadata SET value = :v WHERE key = :k"), {"v": json.dumps(dirty), "k": chain_store.chain_key(sym, exp)})
            await s.commit()
            res = await check_chain_quality(s)
            assert res.level == ERROR and any(r.startswith(f"chain:{sym}:{exp}: ") and "1 price" in r and "1 duplicate" in r for r in res.rows)
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :k"), {"k": f"chain:{sym}:%"})
            await s.commit()
