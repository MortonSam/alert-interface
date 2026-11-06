"""Build a Trade drafts from rules, with no model call (Sam, 2026-11-03, as Ivy's Read works): the structure, the strikes and the
target come from the risk level, the options' price against the stock's own movement (vol regime) and the move options price, all
from the draft's stored chain; the reasoning is templated (services/draft_copy). These are the rules the model was given
(routers/thesis's old prompt), now applied in code:

    structure   iv_rich: a debit spread, except aggressive (the option outright); iv_cheap: the option outright;
                iv_fair or unknown: conservative a spread, moderate and aggressive the option outright
    long leg    conservative: the strike at the money or just inside it; moderate: the first strike past the price;
                aggressive: the third strike past the price (the prompt's "2 to 4"); always within SINGLE_LEG_MAX of the price
    target      the price moved by TARGET_MULTIPLE x the move options price (0.65, 1, 1.75: the prompt's 0.5-0.8, ~1, 1.5-2),
                or the visitor's own target
    short leg   (a spread) the first strike at or past the target, past the long leg; the spread stands only when its net debit
                is above zero and below its width, otherwise the draft is the option outright
    flags       a target past the largest move after any stored report, or past twice the move options price
"""
from __future__ import annotations

from dataclasses import dataclass

TARGET_MULTIPLE = {"conservative": 0.65, "moderate": 1.0, "aggressive": 1.75}
AGGRESSIVE_STEPS = 3               # strikes past the price for the aggressive draft
SINGLE_LEG_MAX = 0.10              # an outright option's strike stays within 10% of the price (the old rule 8)
IMPLIED_FLAG_MULTIPLE = 2.0


@dataclass
class RuleDraft:
    structure: str                 # "long" | "spread"
    long_strike: float
    long_mid: float
    short_strike: float | None
    short_mid: float | None
    target: float
    flag: str | None               # "beyond_history" | "beyond_implied" | None
    short_reaches: bool = True     # the option sold is at or past the target (False: the farthest priced strike short of it)


def structure_for(risk: str, regime: str | None) -> str:
    """Pure: "spread" or "long"."""
    if regime == "iv_rich":
        return "long" if risk == "aggressive" else "spread"
    if regime == "iv_cheap":
        return "long"
    return "spread" if risk == "conservative" else "long"


def long_leg(direction: str, risk: str, rows: list[dict], spot: float) -> dict | None:
    """Pure: the option bought, from the priced strikes (rows sorted or not)."""
    rows = sorted((r for r in rows if r.get("mid") and r["mid"] > 0 and abs(r["strike"] - spot) / spot <= SINGLE_LEG_MAX),
                  key=lambda r: r["strike"])
    if not rows:
        return None
    bull = direction == "bullish"
    inside = [r for r in rows if (r["strike"] <= spot if bull else r["strike"] >= spot)]
    past = [r for r in rows if (r["strike"] > spot if bull else r["strike"] < spot)]
    if not bull:
        past = past[::-1]                       # nearest first
    atm = (inside[-1] if bull else inside[0]) if inside else None
    if risk == "conservative":
        return atm or (past[0] if past else None)
    if risk == "moderate":
        return past[0] if past else atm
    return past[min(AGGRESSIVE_STEPS, len(past)) - 1] if past else atm


def short_leg(direction: str, rows: list[dict], long_k: float, target: float) -> dict | None:
    """Pure: the option sold, the first priced strike at or past the target and past the long leg (the farthest past the long leg
    when none reaches the target)."""
    bull = direction == "bullish"
    beyond = sorted((r for r in rows if r.get("mid") and r["mid"] > 0 and (r["strike"] > long_k if bull else r["strike"] < long_k)),
                    key=lambda r: r["strike"], reverse=not bull)
    if not beyond:
        return None
    reach = [r for r in beyond if (r["strike"] >= target if bull else r["strike"] <= target)]
    return reach[0] if reach else beyond[-1]


def target_for(direction: str, risk: str, spot: float, implied_pct: float) -> float:
    """Pure: the price moved by the risk level's share of the move options price (implied_pct a fraction, 0.087 for 8.7%)."""
    move = TARGET_MULTIPLE[risk] * implied_pct
    return round(spot * (1 + move if direction == "bullish" else 1 - move), 2)


def flag_for(target: float, spot: float, implied_pct: float | None, hist_max: float | None) -> str | None:
    move = abs(target - spot) / spot
    if hist_max and move > hist_max:
        return "beyond_history"
    if implied_pct and move > IMPLIED_FLAG_MULTIPLE * implied_pct:
        return "beyond_implied"
    return None


def draft(direction: str, risk: str, regime: str | None, rows: list[dict], spot: float, implied_pct: float | None,
          hist_max: float | None, proposed_target: float | None = None) -> RuleDraft | None:
    """Pure: the draft, or None when the chain gives no option to buy or no move to aim at."""
    leg = long_leg(direction, risk, rows, spot)
    if leg is None or (proposed_target is None and not implied_pct):
        return None
    target = round(proposed_target, 2) if proposed_target is not None else target_for(direction, risk, spot, implied_pct)
    flag = flag_for(target, spot, implied_pct, hist_max)
    if structure_for(risk, regime) == "spread":
        sold = short_leg(direction, rows, leg["strike"], target)
        if sold is not None:
            debit = round(leg["mid"] - sold["mid"], 2)
            if 0 < debit < abs(sold["strike"] - leg["strike"]):
                reaches = sold["strike"] >= target if direction == "bullish" else sold["strike"] <= target
                return RuleDraft("spread", leg["strike"], leg["mid"], sold["strike"], sold["mid"], target, flag, reaches)
    return RuleDraft("long", leg["strike"], leg["mid"], None, None, target, flag)


# ── The budget alternative (Sam, 2026-11-06: no part of drafting uses the model) ─────────────────────────────────────────────
# The old prompt's search order, applied in code: 1. a spread whose net debit fits the budget, keeping the option the draft bought
# (or the next strike out when even its narrowest spread does not fit); 2. a single option further from the money that fits;
# 3. nothing. Its guard against a lottery ticket: the option bought is at most ALT_MAX_STEPS strikes from the money, and anything
# costing under ALT_MIN_COST for one contract is refused; like the draft's, it stays within SINGLE_LEG_MAX of the price.
ALT_MAX_STEPS = 3
ALT_MIN_COST = 50.0


@dataclass
class Alternative:
    structure: str                 # "spread" | "long"
    long_strike: float
    long_mid: float
    short_strike: float | None
    short_mid: float | None
    cost: float                    # for one contract, in dollars

    @property
    def debit(self) -> float:
        return round(self.long_mid - (self.short_mid or 0.0), 2)


@dataclass
class NoAlternative:
    reason: str                    # "no_options" | "too_far" | "too_cheap"
    cheapest: float | None = None  # the cheapest structure within reach, for one contract (too_far)


def _priced(rows: list[dict]) -> list[dict]:
    return sorted((r for r in rows if r.get("mid") and r["mid"] > 0), key=lambda r: r["strike"])


def steps_from_money(direction: str, rows: list[dict], spot: float, strike: float) -> int:
    """Pure: how many priced strikes `strike` sits past the at-the-money one (0 at or inside it)."""
    ks = [r["strike"] for r in _priced(rows)]
    if direction == "bullish":
        return sum(1 for k in ks if spot < k <= strike)
    return sum(1 for k in ks if strike <= k < spot)


def alternative(direction: str, rows: list[dict], spot: float, budget: float, best_long: float,
                target: float | None) -> Alternative | NoAlternative:
    """Pure: the cheaper alternative to a draft that buys `best_long`, under `budget` dollars for one contract."""
    bull = direction == "bullish"
    priced = _priced(rows)
    if not priced:
        return NoAlternative("no_options")
    outward = priced if bull else priced[::-1]                          # strikes in the direction of the bet
    reach = [r for r in outward if steps_from_money(direction, rows, spot, r["strike"]) <= ALT_MAX_STEPS
             and abs(r["strike"] - spot) / spot <= SINGLE_LEG_MAX]
    longs = [r for r in reach if (r["strike"] >= best_long if bull else r["strike"] <= best_long)]
    cheapest: float | None = None      # the cheapest structure within reach that is not a lottery ticket
    lottery = False                    # something under the budget was refused for costing under ALT_MIN_COST

    def consider(cost: float) -> bool:
        nonlocal cheapest, lottery
        if cost < ALT_MIN_COST:
            lottery = lottery or cost <= budget
            return False
        cheapest = cost if cheapest is None else min(cheapest, cost)
        return cost <= budget

    # 1. a spread: the option bought, then the widest spread that fits, its option sold never past the first strike at the target
    for leg in longs:
        past = [r for r in outward if (r["strike"] > leg["strike"] if bull else r["strike"] < leg["strike"])]
        if target is not None:
            at = next((i for i, r in enumerate(past) if (r["strike"] >= target if bull else r["strike"] <= target)), None)
            past = past if at is None else past[:at + 1]
        fits = []
        for sold in past:
            debit = round(leg["mid"] - sold["mid"], 2)
            if 0 < debit < abs(sold["strike"] - leg["strike"]) and consider(round(debit * 100, 2)):
                fits.append(Alternative("spread", leg["strike"], leg["mid"], sold["strike"], sold["mid"], round(debit * 100, 2)))
        if fits:
            return max(fits, key=lambda a: abs(a.short_strike - a.long_strike))
    # 2. a single option further from the money than the draft's
    for leg in longs:
        if leg["strike"] != best_long and consider(round(leg["mid"] * 100, 2)):
            return Alternative("long", leg["strike"], leg["mid"], None, None, round(leg["mid"] * 100, 2))
    # 3. nothing fits
    if lottery and (cheapest is None or cheapest > budget):
        return NoAlternative("too_cheap", cheapest)
    return NoAlternative("too_far", cheapest)
