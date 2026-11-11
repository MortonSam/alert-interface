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


# 1. why this structure: the swings the options are pricing in against the swings the stock has made (plain words, Sam 2026-11-10:
#    no "points of movement"; spread_pp, implied less realized volatility, picks the regime and is not shown)
SWINGS = "over the last 20 trading days"


def vol_sentence(sym: str, regime: str | None, spread_pp: float | None, structure: str) -> str:
    if regime == "iv_rich" and spread_pp is not None:
        why = f"Options on {sym} are pricing in bigger swings than the stock has actually made {SWINGS}"
        return why + (", so the draft is a spread, where the option sold pays for part of the one bought." if structure == "spread"
                      else ". The aggressive draft buys the option outright anyway, for the larger gain if the stock moves far.")
    if regime == "iv_cheap" and spread_pp is not None:
        return (f"Options on {sym} are pricing in smaller swings than the stock has actually made {SWINGS}, "
                f"so buying the option outright doesn't mean paying extra for big swings.")
    why = f"Options on {sym} are pricing in about the same swings the stock has actually made {SWINGS}"
    if structure == "spread":
        return why + ", and the conservative draft is a spread, which costs less and caps the gain."
    return why + ", so the draft buys the option outright."


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


# ── The budget alternative (services/draft_rules.alternative) ─────────────────────────────────────────────────────────────
def alt_tradeoff_spread(direction: str, kind: str, best_long: float, best_short: float | None, max_gain: float,
                        best_max_gain: float | None) -> str:
    if best_short is not None and best_max_gain is not None:
        return f"The gain stops at ${max_gain:,.0f} for one contract, against ${best_max_gain:,.0f} for the ${best_long:g}/${best_short:g} spread."
    if direction == "bullish":
        return f"The gain stops at ${max_gain:,.0f} for one contract, where the ${best_long:g} {kind} alone has no cap."
    return f"The gain stops at ${max_gain:,.0f} for one contract, where the ${best_long:g} {kind} alone gains more the further the stock falls."


def alt_tradeoff_long(direction: str, kind: str, strike: float, breakeven: float, best_long: float, best_breakeven: float) -> str:
    side = "above" if direction == "bullish" else "below"
    return (f"The stock has to finish {side} ${breakeven:,.2f} by expiration to come out ahead, against ${best_breakeven:,.2f} "
            f"for the ${best_long:g} {kind}.")


def alt_reasoning_spread(kind: str, budget: float, best_cost: float, long_k: float, long_mid: float, short_k: float,
                         short_mid: float, cost: float, best_long: float | None = None) -> str:
    moved = (f" No spread from the draft's ${best_long:g} {kind} fits, so this one starts further out."
             if best_long is not None and best_long != long_k else "")
    return (f"Your budget of ${budget:,.0f} is below the ${best_cost:,.0f} the draft costs.{moved} The ${long_k:g} {kind} bought is "
            f"${long_mid:.2f} a share and the ${short_k:g} {kind} sold brings in ${short_mid:.2f}, so one contract costs ${cost:,.0f}. "
            f"It is the widest spread from that strike that fits the budget.")


def alt_reasoning_long(kind: str, budget: float, best_cost: float, strike: float, mid: float, cost: float) -> str:
    return (f"Your budget of ${budget:,.0f} is below the ${best_cost:,.0f} the draft costs, and no spread from its strike fits. "
            f"The ${strike:g} {kind} is the nearest strike further out that does: ${mid:.2f} a share, ${cost:,.0f} for one contract.")


def alt_none(reason: str, sym: str, budget: float, steps: int, min_cost: float, cheapest: float | None) -> str:
    if reason == "no_options":
        return f"No priced options on {sym} for this expiration, so there is no cheaper version of this trade to show."
    if reason == "too_cheap":
        return (f"Only options costing under ${min_cost:,.0f} for one contract fit a budget of ${budget:,.0f}, and Ivy doesn't suggest "
                f"those. A larger budget or a stock with a lower price would leave more room.")
    tail = f" The cheapest costs ${cheapest:,.0f} for one contract." if cheapest is not None else ""
    return (f"Nothing within {steps} strikes of the stock's price fits a budget of ${budget:,.0f}.{tail} "
            f"A larger budget or a stock with a lower price would leave more room.")
