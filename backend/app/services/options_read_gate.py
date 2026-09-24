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


# ── Staleness by fact: a cached read that says "(unavailable)" for something
# the stores now serve is not served again. Keyed by servability group; the
# endpoint and the validate check compute {group: servable_now} the same way.
SERVABLE_GROUPS: dict[str, tuple[str, ...]] = {
    "rv": ("rv_20d", "rv_rank", "rv_percentile", "rv_min_1y", "rv_max_1y"),   # rv_store.get_servable_rv
    "atm_iv": ("atm_iv",),                                                     # iv_history within 3 days
    "earnings_history": ("avg_earnings_1d_move_pct",),                         # reactions exist, ticker not excluded
}
FACT_LABELS = {"rv": "realized volatility", "atm_iv": "implied volatility", "earnings_history": "earnings history"}


def stale_facts(fact_values: dict | None, servable_now: dict[str, bool] | None) -> list[str]:
    """Fact keys that are null in the block while their group is servable now."""
    if not fact_values or not servable_now:
        return []
    out: list[str] = []
    for group, keys in SERVABLE_GROUPS.items():
        if servable_now.get(group):
            out.extend(k for k in keys if fact_values.get(k) is None)
    return out


def stale_reason(fact_key: str) -> str:
    """Visitor-facing: why a read is being regenerated."""
    group = next((g for g, keys in SERVABLE_GROUPS.items() if fact_key in keys), fact_key)
    return (f"Ivy's Read was written when {FACT_LABELS.get(group, group)} was unavailable and is being "
            f"regenerated now that it is")


async def load_cached_read_status(
    get_meta: Callable[[str], Awaitable[str | None]],
    symbol: str,
    chain_date: str | None,
    chain_is_fresh: bool,
    servable_now: dict[str, bool] | None = None,
    log: Callable[[str], None] = print,
) -> tuple[dict | None, str | None]:
    """(read, None) when the stored read may be served; (None, fact_key) when it is stale; (None, None) when absent.

    The one way to read what the options-read endpoint cached: it uses the same
    key function as the writer and the same chain freshness gate, so a consumer
    (the /explain tooltips) can never look under a key nobody writes, and never
    gets values from a stale chain. With `servable_now`, a read whose block has
    a null fact that the stores now serve is stale: not served, and the warm
    regenerates it. The cached facts were themselves built under the fresh-quote gate.
    """
    if not check_chain(chain_date, chain_is_fresh).ok:
        return None, None
    raw = await get_meta(cache_key(symbol, chain_date))
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    stale = stale_facts(data.get("fact_values"), servable_now)
    if stale:
        log(f"[options-read] {symbol}: cached read for chain {chain_date} is stale: "
            f"{stale[0]} is null in its fact block but servable now (regenerate)")
        return None, stale[0]
    return data, None


async def load_cached_read(
    get_meta: Callable[[str], Awaitable[str | None]],
    symbol: str,
    chain_date: str | None,
    chain_is_fresh: bool,
    servable_now: dict[str, bool] | None = None,
) -> dict | None:
    """The stored Ivy's Read for the current chain, or None (absent or stale)."""
    return (await load_cached_read_status(get_meta, symbol, chain_date, chain_is_fresh, servable_now))[0]


# ── The fact block ────────────────────────────────────────────────────────────
# One numeric block is the source of everything a read says AND of the rows
# shown beside it. format_facts turns it into the strings the model sees; the
# frontend renders the rows from the same numbers while the read is displayed.

FACT_VALUE_KEYS = (
    "current_price", "price_as_of", "chain_date",
    "expected_move_pct", "expected_move_dollars", "implied_range_low", "implied_range_high",
    "expiration_used", "days_to_expiration", "atm_strike", "atm_iv", "atm_iv_as_of",
    "atm_iv_reason",                  # why atm_iv is null (iv_store's reason)
    "next_earnings_date", "expiration_spans_earnings", "days_exp_past_earnings",
    "rv_20d", "rv_rank", "rv_percentile", "rv_min_1y", "rv_max_1y", "rv_sample_days",
    "rv_reason", "rv_as_of",          # why RV is absent (rv_store's reason) and the snapshot date it came from
    "iv_rv_spread_pp", "avg_earnings_1d_move_pct", "earnings_sample_size",
)


def format_facts(symbol: str, company_name: str, v: dict) -> dict:
    """The strings injected into the prompt, formatted from the numeric fact block only."""
    def fp(x, d: int = 2) -> str:
        return f"${x:.{d}f}" if x is not None else "(unavailable)"

    def fpct(x, d: int = 1) -> str:
        return f"{x * 100:.{d}f}%" if x is not None else "(unavailable)"

    lo, hi = v.get("implied_range_low"), v.get("implied_range_high")
    rmin, rmax = v.get("rv_min_1y"), v.get("rv_max_1y")
    return {
        "symbol": symbol,
        "company_name": company_name,
        "current_price": fp(v.get("current_price")),
        "expected_move_pct": f"±{v['expected_move_pct'] * 100:.1f}%" if v.get("expected_move_pct") is not None else "(unavailable)",
        "expected_move_dollars": f"±{fp(v['expected_move_dollars'])}" if v.get("expected_move_dollars") is not None else "(unavailable)",
        "implied_range": f"{fp(lo)} - {fp(hi)}" if lo is not None and hi is not None else "(unavailable)",
        "expiration_date": v.get("expiration_used") or "(unavailable)",
        "days_to_expiration": str(v["days_to_expiration"]) if v.get("days_to_expiration") is not None else "(unavailable)",
        "atm_strike": fp(v.get("atm_strike")),
        "atm_iv": (fpct(v["atm_iv"]) if v.get("atm_iv") is not None
                   else f"(unavailable: {v['atm_iv_reason']})" if v.get("atm_iv_reason") else "(unavailable)"),
        "next_earnings_date": v.get("next_earnings_date") or "(unavailable)",
        "expiration_spans_earnings": str(bool(v.get("expiration_spans_earnings"))),
        "days_exp_past_earnings": str(v["days_exp_past_earnings"]) if v.get("days_exp_past_earnings") is not None else "N/A",
        "realized_vol_20d": (fpct(v["rv_20d"]) if v.get("rv_20d") is not None
                             else f"(unavailable: {v['rv_reason']})" if v.get("rv_reason") else "(unavailable)"),
        "rv_as_of": v.get("rv_as_of") or "(unavailable)",
        "rv_rank": f"{v['rv_rank']:.1f}" if v.get("rv_rank") is not None else "(unavailable)",
        "rv_percentile": f"{v['rv_percentile']:.1f}" if v.get("rv_percentile") is not None else "(unavailable)",
        "rv_1yr_range": f"{fpct(rmin)} - {fpct(rmax)}" if rmin is not None and rmax is not None else "(unavailable)",
        "rv_sample_days": str(v.get("rv_sample_days") or 0),
        "iv_rv_spread": f"{v['iv_rv_spread_pp']:+.1f}pp" if v.get("iv_rv_spread_pp") is not None else "(unavailable)",
        "avg_earnings_1d_move": f"±{v['avg_earnings_1d_move_pct']:.1f}%" if v.get("avg_earnings_1d_move_pct") is not None else "(unavailable)",
        "earnings_sample_size": str(v["earnings_sample_size"]) if v.get("earnings_sample_size") else "(unavailable)",
    }
