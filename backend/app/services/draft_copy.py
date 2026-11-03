"""Every sentence a rules-built Build a Trade draft says (services/draft_rules), DRAFT, held for Sam's approval
(docs/build_a_trade_wording.md section D). Each figure is filled from the draft's own fact block; no model writes any of it.
No sentence tells anyone to buy or sell: each says what the draft is and why its parts were chosen.
"""
from __future__ import annotations

KIND = {"bullish": "call", "bearish": "put"}
SPREAD_NAME = {"bullish": "Bull call spread", "bearish": "Bear put spread"}

# the strategy line (the same shape the model was asked for, so the page reads it unchanged)
def strategy_long(strike: float, kind: str, mid: float) -> str:
    return f"Long ${strike:g} {kind} (${mid:.2f} mid)"


def strategy_spread(direction: str, long_k: float, short_k: float, debit: float) -> str:
    return f"{SPREAD_NAME[direction]} ${long_k:g}/${short_k:g} (${debit:.2f} net debit)"


# 1. why this structure: the options' price against how much the stock has moved
def vol_sentence(sym: str, regime: str | None, spread_pp: float | None, structure: str) -> str:
    if regime == "iv_rich" and spread_pp is not None:
        why = (f"Options on {sym} are priced for {spread_pp:.1f} points more movement than the stock has shown over the last 20 trading days")
        return why + (", so the draft is a spread, where the option sold pays for part of the one bought." if structure == "spread"
                      else ". The aggressive draft buys the option outright anyway, for the larger gain if the stock moves far.")
    if regime == "iv_cheap" and spread_pp is not None:
        return (f"Options on {sym} are priced for {abs(spread_pp):.1f} points less movement than the stock has shown over the last 20 trading days, "
                f"so buying the option outright doesn't pay extra for movement.")
    if structure == "spread":
        return f"Options on {sym} are priced close to how much the stock has moved lately, and the conservative draft is a spread, which costs less and caps the gain."
    return f"Options on {sym} are priced close to how much the stock has moved lately, so the draft buys the option outright."


# 2. the stock's own history after reports
def history_sentence(sym: str, n: int, avg_pct: float, max_pct: float) -> str:
    return f"After its last {n} reports, {sym} moved {avg_pct:.1f}% on a typical report day, and {max_pct:.1f}% at most."


# 3. the target, against the move options price by the expiration
TARGET_SHARE = {"conservative": "about two thirds of", "moderate": "about", "aggressive": "about 1.75 times"}


def target_sentence(target: float, risk: str, implied_pct: float, expiration: str) -> str:
    return (f"The target, ${target:.2f}, is {TARGET_SHARE[risk]} the ±{implied_pct:.1f}% move options price by {expiration}, "
            f"the {risk} choice.")


def target_own(target: float) -> str:
    return f"The target, ${target:.2f}, is the one you entered."


# 4. the strike, by risk level
STRIKE_WHY = {
    "conservative": "The {kind} bought is at the money or just inside it, so less of its price is a bet on the move.",
    "moderate": "The {kind} bought is the first strike past the stock's price.",
    "aggressive": "The {kind} bought is a few strikes past the stock's price. It costs less and needs a bigger move.",
}


def strike_sentence(risk: str, kind: str) -> str:
    return STRIKE_WHY[risk].format(kind=kind)


def spread_sentence(kind: str, short_k: float, reaches: bool = True) -> str:
    if reaches:
        return f"The {kind} sold, at ${short_k:g}, sits at or just past the target and caps the gain there."
    return f"The {kind} sold, at ${short_k:g}, is the farthest priced strike toward the target, so the gain stops there, short of the target."


# 5. analysts, when there is a measured median (at least three sessions)
def analyst_sentence(sym: str, direction: str, n: int, median_pct: float) -> str:
    what = "upgrades" if direction == "bullish" else "downgrades"
    return f"After {n} analyst {what}, {sym}'s median move the next day was {median_pct:+.2f}%."


# the realism flags (shown above the draft)
def flag_beyond_history(target: float, move_pct: float, max_pct: float, n: int) -> str:
    return (f"A target of ${target:.2f} needs a {move_pct:.1f}% move, more than the largest move after any of its last {n} reports "
            f"({max_pct:.1f}%).")


def flag_beyond_implied(target: float, move_pct: float, implied_pct: float) -> str:
    return f"A target of ${target:.2f} needs a {move_pct:.1f}% move, more than twice the ±{implied_pct:.1f}% options price."
