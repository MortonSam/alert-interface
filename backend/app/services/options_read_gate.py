"""Whether Ivy's Read may be generated or served for a ticker.

A read narrates an options chain against a current price. Without a fresh chain
and a fresh quote there is nothing true to narrate, so the read is absent with a
reason. Reasons here are shown to visitors: plain language only.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from app.services.price_freshness import QuoteState, assess_quote

# Bumped when the conditions for generating a read change, so older reads are not reused.
# v4: reads need a fresh chain and a fresh quote.
OPTIONS_READ_CACHE_VERSION = "v4"


def cache_key(symbol: str, chain_date: str) -> str:
    return f"options_read:{OPTIONS_READ_CACHE_VERSION}:{symbol}:{chain_date}"


@dataclass(frozen=True)
class ReadGate:
    ok: bool
    reason: str | None        # visitor-facing
    detail: str | None        # for logs
    quote: QuoteState | None = None


def check_chain(chain_date: str | None, chain_is_fresh: bool) -> ReadGate:
    """Applies to cached reads too: a read about an old chain is not served."""
    if not chain_date:
        return ReadGate(False, "No options data is available for this ticker", "no ingested chain")
    if not chain_is_fresh:
        return ReadGate(False, f"Options data was last updated {chain_date} and is no longer current",
                        f"chain_last_trade={chain_date} is stale")
    return ReadGate(True, None, None)


def check_generation_inputs(
    chain_date: str | None,
    chain_is_fresh: bool,
    n_calls: int,
    n_puts: int,
    quote_price: float | None,
    quote_timestamp: int | None,
    today: date | None = None,
) -> ReadGate:
    """Everything a new read needs: a fresh chain with contracts, and a fresh quote."""
    chain = check_chain(chain_date, chain_is_fresh)
    if not chain.ok:
        return chain
    if n_calls == 0 or n_puts == 0:
        return ReadGate(False, "No usable options contracts are available for this ticker",
                        f"chain {chain_date}: calls={n_calls} puts={n_puts}")
    quote = assess_quote(quote_price, quote_timestamp, today)
    if quote.state != "ok":
        return ReadGate(False, quote.reason, f"quote state={quote.state} traded_on={quote.traded_on}", quote)
    return ReadGate(True, None, None, quote)


async def load_cached_read(
    get_meta: Callable[[str], Awaitable[str | None]],
    symbol: str,
    chain_date: str | None,
    chain_is_fresh: bool,
) -> dict | None:
    """The stored Ivy's Read for the current chain, or None.

    The one way to read what the options-read endpoint cached: it uses the same
    key function as the writer and the same chain freshness gate, so a consumer
    (the /explain tooltips) can never look under a key nobody writes, and never
    gets values from a stale chain. The cached facts were themselves built under
    the fresh-quote gate.
    """
    if not check_chain(chain_date, chain_is_fresh).ok:
        return None
    raw = await get_meta(cache_key(symbol, chain_date))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
