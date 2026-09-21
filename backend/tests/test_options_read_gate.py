"""Ivy's Read must not be generated, or served, without a fresh chain and a fresh quote."""
from datetime import date, datetime, timezone

from app.services.options_read_gate import check_chain, check_generation_inputs
from app.services.price_freshness import assess_quote

TODAY = date(2026, 9, 21)                       # Monday


def _ts(y, m, d) -> int:
    return int(datetime(y, m, d, 20, 0, tzinfo=timezone.utc).timestamp())


def test_stale_quote_is_never_a_current_price():
    # EQR locally: Finnhub returned 65.35 with a last trade on 2026-09-04.
    q = assess_quote(65.35, _ts(2026, 9, 4), today=TODAY)
    assert q.price is None and q.state == "stale"
    assert "2026-09-04" in q.reason
    fresh = assess_quote(339.07, _ts(2026, 9, 18), today=TODAY)
    assert fresh.price == 339.07 and fresh.state == "ok"


def test_quote_without_a_price_or_trade_time_is_absent():
    assert assess_quote(None, _ts(2026, 9, 18), today=TODAY).price is None
    assert assess_quote(0, _ts(2026, 9, 18), today=TODAY).price is None
    assert assess_quote(100.0, None, today=TODAY).state == "no_data"


def test_no_chain_means_no_read_and_no_chain_date():
    gate = check_chain(None, False)
    assert not gate.ok and gate.reason == "No options data is available for this ticker"
    full = check_generation_inputs(None, False, 0, 0, 100.0, _ts(2026, 9, 18), today=TODAY)
    assert not full.ok and full.reason == gate.reason


def test_stale_chain_blocks_cached_and_new_reads_and_names_the_chain_date():
    gate = check_chain("2026-08-14", False)
    assert not gate.ok
    assert "2026-08-14" in gate.reason          # the label comes from the chain, never from today
    assert TODAY.isoformat() not in gate.reason


def test_generation_refused_when_every_input_is_unavailable():
    # Fresh chain key but no contracts, and a stale quote: nothing true to narrate.
    no_contracts = check_generation_inputs("2026-09-18", True, 0, 0, 100.0, _ts(2026, 9, 18), today=TODAY)
    assert not no_contracts.ok and "contracts" in no_contracts.reason
    stale_quote = check_generation_inputs("2026-09-18", True, 40, 40, 65.35, _ts(2026, 9, 4), today=TODAY)
    assert not stale_quote.ok and stale_quote.quote.state == "stale"


def test_generation_allowed_with_fresh_chain_and_quote():
    gate = check_generation_inputs("2026-09-18", True, 40, 38, 339.07, _ts(2026, 9, 18), today=TODAY)
    assert gate.ok and gate.reason is None and gate.quote.price == 339.07


def test_reasons_are_plain_language():
    reasons = [
        check_chain(None, False).reason,
        check_chain("2026-08-14", False).reason,
        check_generation_inputs("2026-09-18", True, 0, 5, 1.0, _ts(2026, 9, 18), today=TODAY).reason,
        assess_quote(65.35, _ts(2026, 9, 4), today=TODAY).reason,
        assess_quote(None, None, today=TODAY).reason,
    ]
    for r in reasons:
        assert r and not any(tok in r for tok in ("status", "snapshot", "'", "_", "None", "sessions"))


# ── The stored read has one key, used by its writer and by every reader ──────

import asyncio
import json
import re
from pathlib import Path

from app.services.options_read_gate import cache_key, load_cached_read


def _store(contents: dict):
    async def get_meta(key: str):
        return contents.get(key)
    return get_meta


def test_reader_finds_what_the_writer_stored():
    written = {cache_key("AAPL", "2026-09-18"): json.dumps({"iv_rv_spread_pp": 3.2, "facts": {"atm_iv": "24.6%"}})}
    got = asyncio.run(load_cached_read(_store(written), "AAPL", "2026-09-18", True))
    assert got["iv_rv_spread_pp"] == 3.2 and got["facts"]["atm_iv"] == "24.6%"


def test_reader_does_not_look_under_the_old_per_day_key():
    # /explain used to read options_read:{sym}:{today}, which nothing ever wrote.
    old_style = {"options_read:AAPL:2026-09-21": json.dumps({"iv_rv_spread_pp": 9.9})}
    assert asyncio.run(load_cached_read(_store(old_style), "AAPL", "2026-09-18", True)) is None


def test_reader_applies_the_chain_freshness_gate():
    written = {cache_key("AAPL", "2026-08-14"): json.dumps({"iv_rv_spread_pp": 3.2})}
    assert asyncio.run(load_cached_read(_store(written), "AAPL", "2026-08-14", False)) is None
    assert asyncio.run(load_cached_read(_store(written), "AAPL", None, False)) is None


def test_corrupt_cache_is_absent_not_an_error():
    assert asyncio.run(load_cached_read(_store({cache_key("X", "2026-09-18"): "{not json"}), "X", "2026-09-18", True)) is None


def test_router_never_spells_the_key_by_hand():
    """Fails if any endpoint reads or writes an options_read key without the shared function."""
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "tickers.py").read_text()
    assert not re.search(r'f?"options_read:', src), "options_read key built by hand in tickers.py"
    assert src.count("options_read_cache_key(") >= 1      # the writer
    assert src.count("_stored_options_read(db, sym)") >= 2  # both /explain readers
