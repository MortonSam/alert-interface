"""The chain a Build a Trade draft reads, in one place for the router (routers/thesis), the nightly Intrinio step
(scripts/shadow_option_chains, which always stores the draft's expiration) and validate's draft_path_fresh check.

    draft_min_expiration(next_report, today)  -> the earliest expiration a draft may use
    draft_target_expiration(listed, next_report, today) -> the first listed expiration on or after it
    pick_draft_chain(db, sym, min_exp)        -> the first stored expiration at or after min_exp whose own chain is fresh,
                                                 else the first stored one (stale), else none
    options_age_refusal(sym, chain_last_trade, today) -> the refusal sentence when the chain is stale, else None

Freshness is chain_store.is_fresh (the NYSE calendar, CHAIN_FRESH_TRADING_DAYS) everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.services import chain_store

DRAFT_DAYS_AFTER_REPORT = 14     # a draft's expiration is at least this many days after the next report
DRAFT_DAYS_WITHOUT_REPORT = 7    # with no report stored, at least this many days after the draft day


def draft_min_expiration(next_report: date | None, today: date) -> str:
    """Pure: the earliest expiration (ISO) a draft on `today` may use."""
    if next_report is not None:
        return (next_report + timedelta(days=DRAFT_DAYS_AFTER_REPORT)).isoformat()
    return (today + timedelta(days=DRAFT_DAYS_WITHOUT_REPORT)).isoformat()


def draft_target_expiration(listed: list[str], min_exp: str) -> str | None:
    """Pure: the first listed expiration on or after min_exp."""
    return next((e for e in sorted(listed) if e >= min_exp), None)


@dataclass(frozen=True)
class DraftChain:
    expiration: str | None
    chain: dict | None
    chain_last_trade: str | None
    fresh: bool


async def pick_draft_chain(db, sym: str, min_exp: str, today: date | None = None) -> DraftChain:
    """The serving source's stored expirations at or after min_exp, in order (chain_store.pick_expiration's rule for the first
    one): the first whose own chain is fresh. When none is fresh, the first stored one, so the draft refuses with that chain's
    date; with none stored, no chain."""
    first = await chain_store.pick_expiration(db, sym, min_exp)
    if first is None:
        return DraftChain(None, None, None, False)
    exps = [e for e in await chain_store.get_ingested_expirations(db, sym) if e >= first]
    fallback: DraftChain | None = None
    for exp in exps:
        got = await chain_store.get_chain(db, sym, exp)
        if not got:
            continue
        chain, clt = got
        if chain_store.is_fresh(clt, today=today):
            return DraftChain(exp, chain, clt, True)
        if fallback is None:
            fallback = DraftChain(exp, chain, clt, False)
    return fallback or DraftChain(first, None, None, False)


def options_age_refusal(sym: str, chain_last_trade: str | None, today: date | None = None) -> str | None:
    """The options-age guard: the refusal sentence when the draft's chain is older than CHAIN_FRESH_TRADING_DAYS sessions, else
    None. No date, no refusal here (the later guards handle a draft with no chain)."""
    if not chain_last_trade or chain_store.is_fresh(chain_last_trade, today=today):
        return None
    return (f"Ivy won't draft {sym} on stale options data "
            f"(as of {chain_last_trade}). "
            f"Options data is updated once a day.")
