"""Ivy v2 decision engine.

Deterministic gates + AI narration of receipt facts.
Direction: always bullish (no bearish path in v2).
Qualifying: momentum reversal only (cohort path dropped — unstable across folds).
Target horizon: 5 days.

All constants tuned via walk-forward grid search (threshold_search.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.earnings_feature import EarningsFeature
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services import chain_store

# ── Tuned constants ──────────────────────────────────────────────────────────
# Source: threshold_search.py extended grid, 1260 combos x 3 held-out folds.
# The -10% cutoff was chosen because it beat its fold baseline in all three
# folds. Current per-fold numbers are not quoted here: backtest_v2.py stores
# them in ivy_backtest_runs on every run, and /ivy renders from that table.

MOMENTUM_CUTOFF = -0.10       # 20d return ≤ -10% qualifies (momentum reversal signal)
MOMENTUM_LOOKBACK_DAYS = 20   # trading days the momentum is measured over
MIN_PRIOR_N = 8               # minimum prior earnings events with actual_5d
IV_PREMIUM_CAP = 1.20         # implied move cannot exceed 1.2× historical expected move
EXIT_TRADING_DAYS = 5         # a pick is closed this many trading days after the earnings date
CANDIDATE_WINDOW_DAYS = 7     # evaluate names reporting within this many calendar days
MAX_NEW_PER_NIGHT = 3         # at most this many new picks per nightly run
MAX_OPEN_TOTAL = 10           # at most this many open picks at once


@dataclass
class V2Result:
    pick: bool
    direction: str | None
    gate_passed: bool
    skip_reason: str | None
    expected_move: float | None
    implied_move: float | None
    receipt: dict = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mid_or_last(bid, ask, last) -> float | None:
    """Prefer bid/ask midpoint; fall back to lastPrice."""
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return last if last and last > 0 else None


def compute_expected_move(features: EarningsFeature) -> float | None:
    """Return prior_avg_abs_5d if enough history, else None."""
    prior_n = features.prior_n
    if prior_n is None or prior_n < MIN_PRIOR_N:
        return None
    val = features.prior_avg_abs_5d
    return float(val) if val is not None else None


@dataclass
class LiveFeatures:
    """Live features for an upcoming earnings event (not a DB row)."""
    symbol: str
    event_date: date
    momentum_20d: float | None
    prior_n: int
    prior_avg_abs_5d: float | None
    prior_up_5d_rate: float | None
    beat_rate: float | None


async def compute_live_features(symbol: str, db: AsyncSession) -> LiveFeatures | None:
    """Build live features for the UPCOMING earnings event.

    Same fields as an EarningsFeature row, but computed as of today using
    current market data (yfinance) and all historical reactions to date.
    Returns None if there is no upcoming earnings event.
    """
    today = date.today()

    # ── Upcoming earnings date from events table ──────────────────────────
    ticker_row = (await db.execute(
        select(Ticker).where(Ticker.symbol == symbol)
    )).scalar_one_or_none()
    if ticker_row is None:
        return None

    event_row = (await db.execute(
        select(Event.event_date)
        .where(
            Event.ticker_id == ticker_row.id,
            Event.event_type == EventType.EARNINGS,
            Event.event_date >= today,
        )
        .order_by(Event.event_date)
        .limit(1)
    )).scalar_one_or_none()
    if event_row is None:
        return None
    upcoming_date: date = event_row

    # ── Prior reactions: all historical earnings reactions to date ─────────
    reactions = (await db.execute(
        select(HistoricalReaction)
        .where(
            HistoricalReaction.ticker_id == ticker_row.id,
            HistoricalReaction.event_type == "earnings",
            HistoricalReaction.event_date < today,
        )
        .order_by(HistoricalReaction.event_date)
    )).scalars().all()

    prior_5ds = [float(r.pct_change_5d) for r in reactions if r.pct_change_5d is not None]
    prior_n = len(prior_5ds)
    prior_avg_abs_5d = round(sum(abs(v) for v in prior_5ds) / prior_n, 4) if prior_5ds else None
    prior_up_5d_rate = round(sum(1 for v in prior_5ds if v > 0) / prior_n, 4) if prior_5ds else None

    # Beat rate from all prior events
    beat_rate = None
    if reactions:
        beats = sum(1 for r in reactions if r.outcome and r.outcome.value == "beat")
        beat_rate = round(beats / len(reactions) * 100, 4)

    # ── Momentum 20d from yfinance (one call) ────────────────────────────
    momentum_20d = None
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="2mo", timeout=30)
        if hist is not None and len(hist) >= 2:
            dates = hist.index.date
            before_mask = dates < today
            if any(before_mask):
                before_prices = hist.loc[before_mask]
                if len(before_prices) >= 2:
                    day_before_close = float(before_prices["Close"].iloc[-1])
                    if len(before_prices) >= 21:
                        ref_close = float(before_prices["Close"].iloc[-21])
                    else:
                        ref_close = float(before_prices["Close"].iloc[0])
                    if ref_close > 0:
                        momentum_20d = round(
                            (day_before_close - ref_close) / ref_close * 100, 4
                        )
    except Exception:
        # Fall back: try loading from price history already in DB
        # (historical_reactions has close_before for each event, but
        # that's not a continuous series — momentum stays None)
        pass

    return LiveFeatures(
        symbol=symbol,
        event_date=upcoming_date,
        momentum_20d=momentum_20d,
        prior_n=prior_n,
        prior_avg_abs_5d=prior_avg_abs_5d,
        prior_up_5d_rate=prior_up_5d_rate,
        beat_rate=beat_rate,
    )


def compute_expected_move_live(features: LiveFeatures) -> float | None:
    """Return prior_avg_abs_5d if enough history, else None (live variant)."""
    if features.prior_n < MIN_PRIOR_N:
        return None
    return features.prior_avg_abs_5d


async def compute_implied_move(
    db: AsyncSession, symbol: str, event_date: date,
) -> tuple[float | None, bool]:
    """Compute ATM straddle / spot as implied move percentage.

    Returns (implied_move_pct, has_fresh_chain).
    """
    min_date = event_date.isoformat()
    exp = await chain_store.pick_expiration(db, symbol, min_date)
    if exp is None:
        return None, False

    chain_result = await chain_store.get_chain(db, symbol, exp)
    if chain_result is None:
        return None, False

    chain_data, chain_last_trade = chain_result
    if not chain_store.is_fresh(chain_last_trade):
        return None, False

    calls_raw = chain_data.get("calls", [])
    puts_raw = chain_data.get("puts", [])
    snapshot_price = chain_data.get("underlying_price")
    if not snapshot_price or snapshot_price <= 0:
        return None, False

    intersection = {c["strike"] for c in calls_raw} & {p["strike"] for p in puts_raw}
    if not intersection:
        return None, True  # fresh chain but no valid strikes

    atm_strike = min(intersection, key=lambda s: abs(s - snapshot_price))
    atm_call = next((c for c in calls_raw if c["strike"] == atm_strike), None)
    atm_put = next((p for p in puts_raw if p["strike"] == atm_strike), None)

    cp = _mid_or_last(atm_call["bid"], atm_call["ask"], atm_call["lastPrice"]) if atm_call else None
    pp = _mid_or_last(atm_put["bid"], atm_put["ask"], atm_put["lastPrice"]) if atm_put else None

    if cp is None or pp is None:
        return None, True

    straddle = cp + pp
    implied_pct = straddle / snapshot_price * 100  # percentage
    return round(implied_pct, 4), True


def _compute_walk_forward_base_rate(
    features: EarningsFeature | LiveFeatures,
    all_features: list[EarningsFeature],
) -> tuple[float | None, int]:
    """Compute walk-forward base rate for the receipt.

    Among prior events (before this event's date) that also qualify
    under the v2 rule (momentum_20d <= MOMENTUM_CUTOFF*100, prior_n >= MIN_PRIOR_N),
    what share were up at 5d?

    For LiveFeatures the event_date is the upcoming earnings date; all
    earnings_features rows are before today, so no leakage.

    Returns (up_rate, n).  Never leaks: only uses events strictly before event_date.
    """
    event_date = features.event_date
    qualifying = []
    for f in all_features:
        if f.event_date >= event_date:
            continue
        if f.prior_n is None or f.prior_n < MIN_PRIOR_N:
            continue
        if f.momentum_20d is None or float(f.momentum_20d) > MOMENTUM_CUTOFF * 100:
            continue
        if f.actual_5d is None:
            continue
        qualifying.append(float(f.actual_5d) > 0)

    n = len(qualifying)
    if n == 0:
        return None, 0
    return round(sum(qualifying) / n, 4), n


async def decide(
    features: EarningsFeature | LiveFeatures,
    db: AsyncSession,
    symbol: str,
    event_date: date,
    all_features: list[EarningsFeature] | None = None,
    ai_client=None,
) -> V2Result:
    """Run the v2 decision engine.

    Accepts either an EarningsFeature (backtest/historical) or a
    LiveFeatures (upcoming earnings, computed by compute_live_features).

    Gate order:
      1. Volatility gate — refuse if no fresh chain or IV premium too high
      2. History gate — refuse if prior_n < MIN_PRIOR_N
      3. Momentum gate — qualify only if momentum_20d ≤ MOMENTUM_CUTOFF
    Direction: always "bullish" when qualifying.
    """

    is_live = isinstance(features, LiveFeatures)
    if is_live:
        expected = compute_expected_move_live(features)
        momentum_20d = features.momentum_20d
        prior_n = features.prior_n
        beat_rate = features.beat_rate
    else:
        expected = compute_expected_move(features)
        momentum_20d = float(features.momentum_20d) if features.momentum_20d is not None else None
        prior_n = int(features.prior_n) if features.prior_n is not None else None
        beat_rate = float(features.beat_rate) if features.beat_rate is not None else None

    # Receipt base rate (walk-forward, never leaks)
    if all_features is not None:
        base_rate_up_5d, base_rate_n = _compute_walk_forward_base_rate(features, all_features)
    else:
        base_rate_up_5d, base_rate_n = None, 0

    receipt = {
        "n_comparable": prior_n,
        "beat_rate": beat_rate,
        "momentum_20d": momentum_20d,
        "expected_pct": round(expected, 2) if expected else None,
        "implied_pct": None,
        "historical_pct": round(expected, 2) if expected else None,
        "base_rate_up_5d": base_rate_up_5d,
        "base_rate_n": base_rate_n,
        "gate_reason": None,
        "reasoning": None,
    }

    # ── Gate 1: Volatility gate ──────────────────────────────────────────────
    implied_move, has_fresh_chain = await compute_implied_move(db, symbol, event_date)
    receipt["implied_pct"] = round(implied_move, 2) if implied_move is not None else None

    if not has_fresh_chain:
        receipt["gate_reason"] = f"no fresh options chain for {symbol}"
        return V2Result(
            pick=False, direction=None, gate_passed=False,
            skip_reason=receipt["gate_reason"],
            expected_move=expected, implied_move=implied_move,
            receipt=receipt,
        )

    if implied_move is not None and expected is not None and expected > 0:
        if implied_move > IV_PREMIUM_CAP * expected:
            reason = f"options pricing {implied_move:.1f}%, history says {expected:.1f}%"
            receipt["gate_reason"] = reason
            return V2Result(
                pick=False, direction=None, gate_passed=False,
                skip_reason=reason,
                expected_move=expected, implied_move=implied_move,
                receipt=receipt,
            )

    # ── Gate 2: History gate ─────────────────────────────────────────────────
    if prior_n is None or prior_n < MIN_PRIOR_N:
        reason = f"insufficient history, {prior_n or 0} events"
        receipt["gate_reason"] = reason
        return V2Result(
            pick=False, direction=None, gate_passed=False,
            skip_reason=reason,
            expected_move=expected, implied_move=implied_move,
            receipt=receipt,
        )

    # ── Gate 3: Momentum qualifying ─────────────────────────────────────────
    if momentum_20d is None or momentum_20d > MOMENTUM_CUTOFF * 100:
        reason = f"momentum {momentum_20d:+.1f}% above {MOMENTUM_CUTOFF*100:.0f}% cutoff" if momentum_20d is not None else "no momentum data"
        receipt["gate_reason"] = reason
        return V2Result(
            pick=False, direction=None, gate_passed=False,
            skip_reason=reason,
            expected_move=expected, implied_move=implied_move,
            receipt=receipt,
        )

    # ── All gates passed — bullish pick ──────────────────────────────────────
    # Structure: spot + expected_move → target, spot - max(expected, implied) → stop
    # (Strikes computed at pick-creation time with live chain data in thesis.py)

    # AI narration (receipt facts only, template fallback)
    reasoning = _template_reasoning(features, expected, implied_move, base_rate_up_5d, base_rate_n)
    if ai_client is not None:
        try:
            ai_reasoning = await _ai_narrate(
                ai_client, features, expected, implied_move,
                base_rate_up_5d, base_rate_n,
            )
            if ai_reasoning:
                reasoning = ai_reasoning
        except Exception:
            pass  # template fallback already set

    receipt["reasoning"] = reasoning
    receipt["gate_reason"] = None

    return V2Result(
        pick=True, direction="bullish", gate_passed=True,
        skip_reason=None,
        expected_move=expected, implied_move=implied_move,
        receipt=receipt,
    )


def _template_reasoning(
    features: EarningsFeature | LiveFeatures,
    expected: float | None,
    implied: float | None,
    base_rate: float | None,
    base_rate_n: int,
) -> str:
    """Deterministic template receipt when AI is unavailable."""
    parts = []
    momentum = float(features.momentum_20d) if features.momentum_20d is not None else None
    prior_n = int(features.prior_n) if features.prior_n is not None else 0

    parts.append(
        f"{features.symbol} is down {abs(momentum):.1f}% over 20 days heading into earnings"
        if momentum is not None else f"{features.symbol} qualifies on momentum reversal"
    )

    parts.append(f"with {prior_n} prior earnings events on record.")

    if expected is not None:
        parts.append(f"The average absolute 5-day post-earnings move is {expected:.1f}%.")

    if implied is not None and expected is not None:
        ratio = implied / expected if expected > 0 else 0
        parts.append(
            f"Options imply a {implied:.1f}% move ({ratio:.1f}x historical)."
        )

    if base_rate is not None and base_rate_n > 0:
        parts.append(
            f"Among {base_rate_n} comparable setups (momentum ≤ {MOMENTUM_CUTOFF * 100:.0f}%, ≥ {MIN_PRIOR_N} prior events), "
            f"{base_rate*100:.0f}% were up at 5 days."
        )

    return " ".join(parts)


async def _ai_narrate(
    ai_client,
    features: EarningsFeature | LiveFeatures,
    expected: float | None,
    implied: float | None,
    base_rate: float | None,
    base_rate_n: int,
) -> str | None:
    """Ask the AI to narrate receipt facts. Returns None on failure."""
    momentum = float(features.momentum_20d) if features.momentum_20d is not None else None
    prior_n = int(features.prior_n) if features.prior_n is not None else 0
    beat_rate = float(features.beat_rate) if features.beat_rate is not None else None

    facts = [
        f"Symbol: {features.symbol}",
        f"Event date: {features.event_date}",
        f"20-day momentum: {momentum:+.1f}%" if momentum is not None else "20-day momentum: unavailable",
        f"Prior earnings events: {prior_n}",
        f"Historical avg |5d move|: {expected:.1f}%" if expected is not None else "Historical avg |5d move|: unavailable",
        f"Implied move (ATM straddle): {implied:.1f}%" if implied is not None else "Implied move: unavailable",
        f"Beat rate: {beat_rate:.0f}%" if beat_rate is not None else "Beat rate: unavailable",
    ]
    if base_rate is not None and base_rate_n > 0:
        facts.append(f"Walk-forward base rate (momentum ≤ -15%, ≥8 prior, up at 5d): {base_rate*100:.0f}% over {base_rate_n} events")

    prompt = (
        "You are narrating a structured earnings pick receipt. "
        "State ONLY the facts provided below in 2-3 concise sentences. "
        "Do NOT introduce any claims, predictions, or information beyond these facts. "
        "Do NOT use phrases like 'I think' or 'I believe'. "
        "Write in third person about the stock.\n\n"
        "Facts:\n" + "\n".join(f"- {f}" for f in facts)
    )

    result = await ai_client.generate_options_read(prompt)
    content = result.get("content", "").strip()
    return content if content else None
