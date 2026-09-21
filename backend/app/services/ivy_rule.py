"""Ivy's rule as data. The one place copy may get her numbers from.

Every page that states a threshold (the /ivy paragraph, the desk's momentum
highlight, the trades page's exit line, the disclosures page) renders these
values, so the sentence cannot drift from the constant the code applies.
"""
from __future__ import annotations

from app.constants import LEDGER_PUBLIC, LEDGER_START
from app.services import chain_store
from app.services.ivy_v2 import (
    CANDIDATE_WINDOW_DAYS,
    EXIT_TRADING_DAYS,
    IV_PREMIUM_CAP,
    MAX_NEW_PER_NIGHT,
    MAX_OPEN_TOTAL,
    MIN_PRIOR_N,
    MOMENTUM_CUTOFF,
    MOMENTUM_LOOKBACK_DAYS,
)


def ivy_rule() -> dict:
    return {
        "momentum_cutoff_pct": round(MOMENTUM_CUTOFF * 100, 2),   # -10.0: qualifies at or below this
        "momentum_lookback_days": MOMENTUM_LOOKBACK_DAYS,
        "min_prior_quarters": MIN_PRIOR_N,
        "implied_move_multiple": IV_PREMIUM_CAP,
        "exit_trading_days": EXIT_TRADING_DAYS,
        "candidate_window_days": CANDIDATE_WINDOW_DAYS,
        "max_new_picks_per_night": MAX_NEW_PER_NIGHT,
        "max_open_picks": MAX_OPEN_TOTAL,
        "ledger_start": LEDGER_START.isoformat(),
        "ledger_public": LEDGER_PUBLIC,
        "chain_fresh_trading_days": chain_store.CHAIN_FRESH_TRADING_DAYS,
    }
