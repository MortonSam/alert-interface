import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_admin
from app.database import get_db
from app.models.alert_pick import AlertPick
from app.models.analyst_reaction_stats import AnalystReactionStats
from app.models.enums import EarningsOutcome, EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.thesis import Thesis, ThesisStatus
from app.models.ticker import Ticker
from app.schemas.thesis import (
    AlertPickLedgerItem,
    AlertPickRead,
    AlertPickRequest,
    SignalLean,
    ThesisCreate,
    ThesisDraftAlternativeRead,
    ThesisDraftAlternativeRequest,
    ThesisDraftRead,
    ThesisDraftRequest,
    ThesisMarkRead,
    ThesisRead,
    ThesisResolve,
    ThesisStockMarkRead,
)
from app.services.anthropic_client import AnthropicClient
from app.services.finnhub_client import FinnhubClient
from app.services.options_cache import fetch_chain
from app.services.yfinance_client import YFinanceClient

router = APIRouter(prefix="/theses", tags=["theses"])


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _mid_or_last(bid, ask, last):
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return last if last and last > 0 else None


def _to_read(thesis: Thesis) -> ThesisRead:
    read = ThesisRead.model_validate(thesis)
    read.ticker_symbol = thesis.ticker.symbol if thesis.ticker else None
    read.is_due = thesis.target_date <= date.today()
    return read


def _extract_json(text: str) -> dict:
    """Pull first {...} JSON block from model output, tolerating prose and common quirks."""
    match = re.search(r"\{[\s\S]*\}", text)
    raw = match.group() if match else text
    # Sanitize: model sometimes writes "$329.00" as a bare JSON value (invalid).
    raw = re.sub(r":\s*\$([0-9]+(?:\.[0-9]+)?)", r": \1", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse failed after sanitization: {exc}\nText: {raw[:300]}")


def _build_strike_lines(
    side_raw: list[dict],
    atm_strike: float | None,
    current_price: float,
    limit: int = 12,
) -> tuple[str, list[dict]]:
    """Return (formatted text block, list of {strike, mid, iv} dicts) for quality strikes."""
    quality = [c for c in side_raw if (c.get("bid") or 0) > 0 or (c.get("ask") or 0) > 0]
    all_strikes = sorted({c["strike"] for c in quality})
    if atm_strike and atm_strike in all_strikes:
        idx = all_strikes.index(atm_strike)
        keep = set(all_strikes[max(0, idx - (limit // 2)): idx + (limit // 2) + 1])
    else:
        keep = set(all_strikes[:limit])
    rows = []
    for c in quality:
        if c["strike"] not in keep:
            continue
        mid = _mid_or_last(c.get("bid"), c.get("ask"), c.get("lastPrice"))
        if mid is None:
            continue
        iv = c.get("impliedVolatility")
        rows.append({"strike": c["strike"], "mid": round(mid, 2), "iv": round(iv * 100, 1) if iv else None})
    rows.sort(key=lambda r: r["strike"])
    lines = []
    for r in rows:
        dist = r["strike"] - current_price
        dist_str = f"+{dist:.2f}" if dist >= 0 else f"{dist:.2f}"
        atm_tag = "  ← ATM" if r["strike"] == atm_strike else ""
        iv_str = f", IV {r['iv']:.1f}%" if r["iv"] else ""
        lines.append(f"  ${r['strike']:.2f} ({dist_str}): mid ${r['mid']:.2f}{iv_str}{atm_tag}")
    text = "\n".join(lines) if lines else "  (no liquid strikes available)"
    return text, rows


def _canonicalize_spread(
    suggested_strike: float | None,
    spread_strike: float | None,
    direction: str,
) -> tuple[float | None, float | None]:
    """suggested_strike is always the LONG leg. Bull call -> long lower; bear put -> long higher."""
    if suggested_strike is None or spread_strike is None:
        return suggested_strike, spread_strike
    if abs(suggested_strike - spread_strike) < 1e-6:
        return suggested_strike, None  # degenerate -> single leg
    lo, hi = sorted([suggested_strike, spread_strike])
    return (lo, hi) if direction == "bullish" else (hi, lo)


async def _compute_option_mark(
    thesis: Thesis,
    loop: asyncio.AbstractEventLoop,
    stock_price_override: float | None = None,
) -> ThesisMarkRead:
    """Compute mark-to-market P&L for the option leg.

    stock_price_override: skip Finnhub fetch when price is already known (e.g. at resolution).
    """
    as_of = datetime.now(tz=timezone.utc).isoformat()

    if not thesis.option_type or not thesis.strike or not thesis.option_expiration:
        return ThesisMarkRead(
            thesis_id=thesis.id,
            option_type=None, strike=None, strike2=None,
            current_price=None, current_mid1=None, current_mid2=None,
            entry_premium=None, entry_premium2=None, contracts=thesis.contracts or 1,
            pnl_dollars=None, pnl_pct=None,
            mark_basis="no_option_leg", is_expired=False, mark_note=None, as_of=as_of,
        )

    strike1     = float(thesis.strike)
    strike2     = float(thesis.strike2) if thesis.strike2 else None
    entry_prem1 = float(thesis.entry_premium) if thesis.entry_premium else None
    entry_prem2 = float(thesis.entry_premium2) if thesis.entry_premium2 else None
    contracts   = thesis.contracts or 1
    exp_date    = thesis.option_expiration
    today       = date.today()
    is_expired  = today > exp_date
    sym         = thesis.ticker.symbol

    # ── Stock price ────────────────────────────────────────────────────────────
    current_price: float | None = stock_price_override
    if current_price is None:
        finnhub = FinnhubClient()
        try:
            quote = await finnhub.get_quote(sym)
            p = quote.get("c")
            if p and float(p) > 0:
                current_price = float(p)
        except Exception:
            pass
        finally:
            await finnhub.close()

    current_mid1: float | None = None
    current_mid2: float | None = None
    mark_basis = "not_found"
    mark_note: str | None = None

    if is_expired:
        # Settle at intrinsic value
        if current_price is not None:
            if thesis.option_type == "call":
                current_mid1 = max(0.0, current_price - strike1)
                if strike2 is not None:
                    current_mid2 = max(0.0, current_price - strike2)
            else:  # put
                current_mid1 = max(0.0, strike1 - current_price)
                if strike2 is not None:
                    current_mid2 = max(0.0, strike2 - current_price)
            mark_basis = "intrinsic"
            mark_note = f"Expired {exp_date.isoformat()} — settled at intrinsic value"
        else:
            mark_note = f"Expired {exp_date.isoformat()} — could not fetch stock price for intrinsic"
    else:
        # Fetch live chain (cached)
        exp_str = exp_date.isoformat()
        try:
            chain_entry = await fetch_chain(sym, exp_str, loop)
            chain = chain_entry.chain
            as_of = chain_entry.fetched_at.isoformat()
        except Exception as exc:
            mark_note = f"Chain fetch failed: {exc}"
            chain = {"calls": [], "puts": []}

        side = chain.get("calls") if thesis.option_type == "call" else chain.get("puts", [])
        c1 = next((c for c in side if c["strike"] == strike1), None) if side else None
        if c1:
            current_mid1 = _mid_or_last(c1.get("bid"), c1.get("ask"), c1.get("lastPrice"))

        if strike2 is not None:
            c2 = next((c for c in side if c["strike"] == strike2), None) if side else None
            if c2:
                current_mid2 = _mid_or_last(c2.get("bid"), c2.get("ask"), c2.get("lastPrice"))

        if current_mid1 is not None:
            mark_basis = "live_chain"
        else:
            mark_note = mark_note or f"Strike ${strike1:.2f} not found in {exp_str} chain"

    # ── P&L ───────────────────────────────────────────────────────────────────
    pnl_dollars: float | None = None
    pnl_pct: float | None     = None

    if entry_prem1 is not None:
        if strike2 is None:
            # Single leg: (current_mid - entry) × contracts × 100
            if current_mid1 is not None:
                pnl_dollars = (current_mid1 - entry_prem1) * contracts * 100
                if entry_prem1 > 0:
                    pnl_pct = (current_mid1 - entry_prem1) / entry_prem1
        else:
            # Spread: long leg1, short leg2
            # net_current = mid1 - mid2;  net_entry = entry1 - entry2
            if current_mid1 is not None and current_mid2 is not None and entry_prem2 is not None:
                net_current = current_mid1 - current_mid2
                net_entry   = entry_prem1 - entry_prem2
                pnl_dollars = (net_current - net_entry) * contracts * 100
                if net_entry > 0:
                    pnl_pct = (net_current - net_entry) / net_entry

    return ThesisMarkRead(
        thesis_id=thesis.id,
        option_type=thesis.option_type,
        strike=strike1,
        strike2=strike2,
        current_price=current_price,
        current_mid1=current_mid1,
        current_mid2=current_mid2,
        entry_premium=entry_prem1,
        entry_premium2=entry_prem2,
        contracts=contracts,
        pnl_dollars=round(pnl_dollars, 2) if pnl_dollars is not None else None,
        pnl_pct=round(pnl_pct, 4) if pnl_pct is not None else None,
        mark_basis=mark_basis,
        is_expired=is_expired,
        mark_note=mark_note,
        as_of=as_of,
    )


# ── Shared data pipeline ───────────────────────────────────────────────────────

async def _gather_draft_data(sym: str, db: AsyncSession) -> dict:
    """Fetch all market data + DB state needed by both draft and alert-pick endpoints."""
    loop = asyncio.get_event_loop()

    # ── 1. Parallel market data fetch ─────────────────────────────────────────
    finnhub = FinnhubClient()
    try:
        quote, expirations, rv_raw = await asyncio.gather(
            finnhub.get_quote(sym),
            loop.run_in_executor(None, YFinanceClient.get_option_expirations, sym),
            loop.run_in_executor(None, YFinanceClient.get_realized_vol_data, sym),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {exc}")
    finally:
        await finnhub.close()

    current_price: float | None = float(quote.get("c") or 0) or None
    if not current_price:
        raise HTTPException(status_code=422, detail=f"No live price available for {sym}")

    # ── 2. DB: ticker + earnings + reactions ──────────────────────────────────
    ticker_row = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    if not ticker_row:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    today = date.today()
    ned_val = (await db.execute(
        select(func.min(Event.event_date))
        .where(Event.event_type == "earnings", Event.event_date >= today,
               Event.ticker_id == ticker_row.id)
    )).scalar_one_or_none()
    earnings_str: str | None = ned_val.isoformat() if ned_val and hasattr(ned_val, "isoformat") else (str(ned_val) if ned_val else None)

    reactions = (await db.execute(
        select(HistoricalReaction).where(
            HistoricalReaction.ticker_id == ticker_row.id,
            HistoricalReaction.event_type == "earnings",
            HistoricalReaction.pct_change_1d.isnot(None),
        )
    )).scalars().all()

    abs_moves_dec = [abs(float(r.pct_change_1d)) / 100 for r in reactions]
    hist_avg: float | None = mean(abs_moves_dec) if abs_moves_dec else None
    hist_max: float | None = max(abs_moves_dec) if abs_moves_dec else None
    hist_min: float | None = min(abs_moves_dec) if abs_moves_dec else None
    hist_sample: int = len(abs_moves_dec)

    beats = [r for r in reactions if r.outcome == EarningsOutcome.BEAT]
    beat_rate: float | None = len(beats) / len(reactions) * 100 if reactions else None
    beat_drops = [r for r in beats if float(r.pct_change_1d) < 0]
    bbd_rate: float | None = len(beat_drops) / len(beats) * 100 if beats else None

    # ── 2b. Conditional earnings stats ───────────────────────────────────────
    ce_misses = [r for r in reactions if r.outcome == EarningsOutcome.MISS]

    avg_1d_on_beat = round(mean([float(r.pct_change_1d) for r in beats]), 2) if len(beats) >= 3 else None
    median_1d_on_beat = round(median([float(r.pct_change_1d) for r in beats]), 2) if len(beats) >= 3 else None
    avg_1d_on_miss = round(mean([float(r.pct_change_1d) for r in ce_misses]), 2) if len(ce_misses) >= 3 else None
    median_1d_on_miss = round(median([float(r.pct_change_1d) for r in ce_misses]), 2) if len(ce_misses) >= 3 else None

    def _cont_stats(subset):
        with_5d = [(float(r.pct_change_1d), float(r.pct_change_5d)) for r in subset if r.pct_change_5d is not None]
        if len(with_5d) < 3:
            return None, None, len(with_5d)
        avg_5d = round(sum(d5 for _, d5 in with_5d) / len(with_5d), 2)
        cont = sum(1 for d1, d5 in with_5d if (d1 >= 0) == (d5 >= 0))
        return avg_5d, round(cont / len(with_5d) * 100, 1), len(with_5d)

    beat_avg_5d, beat_cont_pct, beat_5d_n = _cont_stats(beats)
    miss_avg_5d, miss_cont_pct, miss_5d_n = _cont_stats(ce_misses)

    abs_1d_sorted = [abs(float(r.pct_change_1d)) for r in sorted(reactions, key=lambda r: r.event_date)]
    recent_4 = abs_1d_sorted[-4:] if len(abs_1d_sorted) >= 4 else []
    prior_4 = abs_1d_sorted[-8:-4] if len(abs_1d_sorted) >= 8 else []
    recent_avg_abs = round(mean(recent_4), 2) if len(recent_4) == 4 else None
    prior_avg_abs = round(mean(prior_4), 2) if len(prior_4) == 4 else None
    magnitude_trend: str | None = None
    if recent_avg_abs and prior_avg_abs and prior_avg_abs > 0.01:
        pct_chg = (recent_avg_abs - prior_avg_abs) / prior_avg_abs
        magnitude_trend = "increasing" if pct_chg > 0.20 else ("decreasing" if pct_chg < -0.20 else "stable")

    # ── 2c. Analyst reaction stats ──────────────────────────────────────────
    analyst_row = await db.scalar(
        select(AnalystReactionStats).where(AnalystReactionStats.symbol == sym)
    )

    # ── 3. Choose expiration ──────────────────────────────────────────────────
    chosen_exp: str | None = None
    if expirations:
        if earnings_str:
            post = [e for e in expirations if e >= earnings_str]
            chosen_exp = post[0] if post else expirations[-1]
        else:
            week_out = (today + timedelta(days=7)).isoformat()
            chosen_exp = next((e for e in expirations if e >= week_out), expirations[0])

    # ── 4. Options chain ──────────────────────────────────────────────────────
    chain: dict = {"calls": [], "puts": []}
    if chosen_exp:
        chain = await loop.run_in_executor(None, YFinanceClient.get_option_chain, sym, chosen_exp)

    calls_raw: list[dict] = chain.get("calls", [])
    puts_raw:  list[dict] = chain.get("puts",  [])

    atm_strike: float | None = None
    expected_move_pct: float | None = None
    expected_move_dollars: float | None = None
    implied_range_low: float | None = None
    implied_range_high: float | None = None
    atm_iv: float | None = None

    intersection = {c["strike"] for c in calls_raw} & {p["strike"] for p in puts_raw}
    if intersection:
        atm_strike = min(intersection, key=lambda s: abs(s - current_price))
        atm_call = next((c for c in calls_raw if c["strike"] == atm_strike), None)
        atm_put  = next((p for p in puts_raw  if p["strike"] == atm_strike), None)
        cp = _mid_or_last(atm_call["bid"], atm_call["ask"], atm_call["lastPrice"]) if atm_call else None
        pp = _mid_or_last(atm_put["bid"],  atm_put["ask"],  atm_put["lastPrice"])  if atm_put  else None
        if cp and pp:
            straddle = cp + pp
            expected_move_pct     = straddle / current_price
            expected_move_dollars = straddle
            implied_range_low     = current_price - straddle
            implied_range_high    = current_price + straddle
        ivs = [c["impliedVolatility"] for c in [atm_call, atm_put]
               if c and c.get("impliedVolatility") is not None]
        atm_iv = sum(ivs) / len(ivs) if ivs else None

    days_to_exp: int | None = (date.fromisoformat(chosen_exp) - today).days if chosen_exp else None

    # ── 5. RV ─────────────────────────────────────────────────────────────────
    current_rv: float | None = rv_raw.get("current_rv")
    rv_series: list[float]   = rv_raw.get("rv_series", [])
    rv_rank: float | None    = None
    if rv_series and current_rv is not None:
        rv_min = min(rv_series); rv_max = max(rv_series)
        rv_rank = (current_rv - rv_min) / (rv_max - rv_min) * 100 if rv_max > rv_min else 50.0
        rv_rank = round(max(0.0, min(100.0, rv_rank)), 1)

    iv_rv_spread_pp: float | None = (
        round((atm_iv - current_rv) * 100, 1)
        if atm_iv is not None and current_rv is not None else None
    )

    # ── 5b. Vol-regime classification ───────────────────────────────────────
    vol_regime: str | None = None
    if iv_rv_spread_pp is not None:
        if iv_rv_spread_pp > 8:
            vol_regime = "iv_rich"
        elif iv_rv_spread_pp < -4:
            vol_regime = "iv_cheap"
        else:
            vol_regime = "iv_fair"

    return {
        "sym": sym,
        "current_price": current_price,
        "ticker_row": ticker_row,
        "earnings_str": earnings_str,
        "reactions": reactions,
        "hist_avg": hist_avg,
        "hist_max": hist_max,
        "hist_min": hist_min,
        "hist_sample": hist_sample,
        "beats": beats,
        "ce_misses": ce_misses,
        "beat_rate": beat_rate,
        "bbd_rate": bbd_rate,
        "avg_1d_on_beat": avg_1d_on_beat,
        "median_1d_on_beat": median_1d_on_beat,
        "avg_1d_on_miss": avg_1d_on_miss,
        "median_1d_on_miss": median_1d_on_miss,
        "beat_cont_pct": beat_cont_pct,
        "beat_5d_n": beat_5d_n,
        "miss_cont_pct": miss_cont_pct,
        "miss_5d_n": miss_5d_n,
        "magnitude_trend": magnitude_trend,
        "analyst_row": analyst_row,
        "chosen_exp": chosen_exp,
        "days_to_exp": days_to_exp,
        "calls_raw": calls_raw,
        "puts_raw": puts_raw,
        "atm_strike": atm_strike,
        "expected_move_pct": expected_move_pct,
        "expected_move_dollars": expected_move_dollars,
        "implied_range_low": implied_range_low,
        "implied_range_high": implied_range_high,
        "atm_iv": atm_iv,
        "current_rv": current_rv,
        "rv_rank": rv_rank,
        "iv_rv_spread_pp": iv_rv_spread_pp,
        "vol_regime": vol_regime,
        "rv_raw": rv_raw,
    }


async def _run_draft_generation(
    data: dict,
    direction: str,
    aggressiveness: str,
    proposed_target: float | None = None,
    extra_prompt_section: str = "",
) -> ThesisDraftRead:
    """Build prompt from gathered data, call AI, parse, and return ThesisDraftRead."""
    sym = data["sym"]
    current_price = data["current_price"]
    earnings_str = data["earnings_str"]
    hist_avg = data["hist_avg"]
    hist_max = data["hist_max"]
    hist_min = data["hist_min"]
    hist_sample = data["hist_sample"]
    beats = data["beats"]
    ce_misses = data["ce_misses"]
    beat_rate = data["beat_rate"]
    bbd_rate = data["bbd_rate"]
    avg_1d_on_beat = data["avg_1d_on_beat"]
    median_1d_on_beat = data["median_1d_on_beat"]
    avg_1d_on_miss = data["avg_1d_on_miss"]
    median_1d_on_miss = data["median_1d_on_miss"]
    beat_cont_pct = data["beat_cont_pct"]
    beat_5d_n = data["beat_5d_n"]
    miss_cont_pct = data["miss_cont_pct"]
    miss_5d_n = data["miss_5d_n"]
    magnitude_trend = data["magnitude_trend"]
    analyst_row = data["analyst_row"]
    chosen_exp = data["chosen_exp"]
    days_to_exp = data["days_to_exp"]
    calls_raw = data["calls_raw"]
    puts_raw = data["puts_raw"]
    atm_strike = data["atm_strike"]
    expected_move_pct = data["expected_move_pct"]
    expected_move_dollars = data["expected_move_dollars"]
    implied_range_low = data["implied_range_low"]
    implied_range_high = data["implied_range_high"]
    atm_iv = data["atm_iv"]
    current_rv = data["current_rv"]
    rv_rank = data["rv_rank"]
    iv_rv_spread_pp = data["iv_rv_spread_pp"]
    vol_regime = data["vol_regime"]

    generated_at = datetime.now(tz=timezone.utc).isoformat()

    # ── 6. Build quality-filtered strike lists ────────────────────────────────
    if direction == "bullish":
        primary_raw, secondary_raw = calls_raw, puts_raw
        primary_label, secondary_label = "CALLS (for bullish position)", "PUTS (for spread second leg)"
        target_1x       = implied_range_high
        target_hist_max = current_price * (1 + (hist_max or 0.08))
        target_hist_max_label = "upside"
    else:  # bearish
        primary_raw, secondary_raw = puts_raw, calls_raw
        primary_label, secondary_label = "PUTS (for bearish position)", "CALLS (for spread second leg)"
        target_1x       = implied_range_low
        target_hist_max = current_price * (1 - (hist_max or 0.08))
        target_hist_max_label = "downside"

    primary_text,   primary_rows   = _build_strike_lines(primary_raw,   atm_strike, current_price)
    secondary_text, secondary_rows = _build_strike_lines(secondary_raw, atm_strike, current_price, limit=8)

    valid_primary_strikes = {r["strike"] for r in primary_rows}

    # ── 7. Realism pre-check ──────────────────────────────────────────────────
    realism_precheck = ""
    if proposed_target is not None:
        pt = proposed_target
        move_req = abs(pt - current_price) / current_price
        realism_precheck = f"\nUSER-PROPOSED TARGET: ${pt:.2f} (requires a {move_req*100:.1f}% move from ${current_price:.2f})\n"
        if hist_max and move_req > hist_max:
            realism_precheck += (
                f"⚠ WARNING: This EXCEEDS {sym}'s largest recorded earnings-day move in the dataset "
                f"({hist_max*100:.1f}% on {hist_sample} quarters). "
                f"\"realism_flag\" MUST warn that this requires a move outside historical range.\n"
            )
        elif expected_move_pct and move_req > 2.0 * expected_move_pct:
            realism_precheck += (
                f"⚠ WARNING: This is {move_req/expected_move_pct:.1f}× the implied expected move "
                f"(±{expected_move_pct*100:.1f}%). "
                f"\"realism_flag\" MUST note this is well beyond the implied range.\n"
            )
        else:
            realism_precheck += "Evaluate whether this target fits the requested aggressiveness profile.\n"

    # ── 8. Build fact_block dict ──────────────────────────────────────────────
    fact_block: dict = {
        "symbol":                    sym,
        "direction":                 direction,
        "aggressiveness":            aggressiveness,
        "current_price":             round(current_price, 2),
        "atm_strike":                atm_strike,
        "earnings_date":             earnings_str,
        "expiration_used":           chosen_exp,
        "days_to_expiration":        days_to_exp,
        "expected_move_pct":         round(expected_move_pct * 100, 2) if expected_move_pct else None,
        "expected_move_dollars":     round(expected_move_dollars, 2) if expected_move_dollars else None,
        "implied_range_low":         round(implied_range_low, 2) if implied_range_low else None,
        "implied_range_high":        round(implied_range_high, 2) if implied_range_high else None,
        "straddle_price":            round(expected_move_dollars, 2) if expected_move_dollars else None,
        "hist_avg_abs_move_pct":     round(hist_avg * 100, 2) if hist_avg else None,
        "hist_max_abs_move_pct":     round(hist_max * 100, 2) if hist_max else None,
        "hist_min_abs_move_pct":     round(hist_min * 100, 2) if hist_min else None,
        "hist_sample_size":          hist_sample,
        "beat_rate_pct":             round(beat_rate, 1) if beat_rate is not None else None,
        "beat_but_dropped_rate_pct": round(bbd_rate, 1) if bbd_rate is not None else None,
        "atm_iv_pct":                round(atm_iv * 100, 1) if atm_iv else None,
        "rv_20d_pct":                round(current_rv * 100, 1) if current_rv else None,
        "rv_rank":                   rv_rank,
        "iv_rv_spread_pp":           iv_rv_spread_pp,
        "vol_regime":                vol_regime,
        # Conditional earnings
        "avg_1d_on_beat":            avg_1d_on_beat,
        "median_1d_on_beat":         median_1d_on_beat,
        "avg_1d_on_miss":            avg_1d_on_miss,
        "median_1d_on_miss":         median_1d_on_miss,
        "beat_continuation_5d_pct":  beat_cont_pct,
        "beat_5d_sample":            beat_5d_n,
        "miss_continuation_5d_pct":  miss_cont_pct,
        "miss_5d_sample":            miss_5d_n,
        "magnitude_trend":           magnitude_trend,
        # Analyst reaction stats
        "upgrade_count":             analyst_row.upgrade_count if analyst_row else 0,
        "median_1d_upgrade":         float(analyst_row.median_1d_upgrade) if analyst_row and analyst_row.median_1d_upgrade is not None else None,
        "upgrade_5d_cont_pct":       float(analyst_row.upgrade_5d_continuation_pct) if analyst_row and analyst_row.upgrade_5d_continuation_pct is not None else None,
        "downgrade_count":           analyst_row.downgrade_count if analyst_row else 0,
        "median_1d_downgrade":       float(analyst_row.median_1d_downgrade) if analyst_row and analyst_row.median_1d_downgrade is not None else None,
        "downgrade_5d_cont_pct":     float(analyst_row.downgrade_5d_continuation_pct) if analyst_row and analyst_row.downgrade_5d_continuation_pct is not None else None,
        "primary_strikes":           primary_rows,
        "secondary_strikes":         secondary_rows,
    }

    # ── 9. Build prompt ───────────────────────────────────────────────────────
    def _n(v, fmt=".2f"): return f"{v:{fmt}}" if v is not None else "(unavailable)"
    def _pct(v, fmt=".1f"): return f"{v*100:{fmt}}%" if v is not None else "(unavailable)"

    em_display  = f"±{expected_move_pct*100:.2f}% (±${expected_move_dollars:.2f})" if expected_move_pct and expected_move_dollars else "(unavailable)"
    ir_display  = f"${implied_range_low:.2f} – ${implied_range_high:.2f}" if implied_range_low and implied_range_high else "(unavailable)"
    t1x_display = f"${target_1x:.2f}" if target_1x else "(unavailable)"
    thmax_display = f"${target_hist_max:.2f} ({target_hist_max_label}, based on hist max ±{hist_max*100:.1f}%)" if hist_max else "(unavailable)"

    # Vol-regime display string
    if vol_regime == "iv_rich":
        vol_regime_display = f"IV RICH (IV {iv_rv_spread_pp:+.1f}pp above RV)"
    elif vol_regime == "iv_cheap":
        vol_regime_display = f"IV CHEAP (IV {iv_rv_spread_pp:+.1f}pp vs RV)"
    elif vol_regime == "iv_fair":
        vol_regime_display = f"IV FAIR (IV {iv_rv_spread_pp:+.1f}pp vs RV)"
    else:
        vol_regime_display = "(unavailable)"

    # Conditional earnings profile section
    ce_lines = []
    if len(beats) >= 3 and avg_1d_on_beat is not None:
        line = f"  On beats (N={len(beats)}): avg 1d {avg_1d_on_beat:+.2f}%, median {median_1d_on_beat:+.2f}%"
        if beat_cont_pct is not None:
            line += f"\n    Follow-through: direction held at day 5 in {beat_cont_pct:.0f}% of cases (N={beat_5d_n})"
        ce_lines.append(line)
    if len(ce_misses) >= 3 and avg_1d_on_miss is not None:
        line = f"  On misses (N={len(ce_misses)}): avg 1d {avg_1d_on_miss:+.2f}%, median {median_1d_on_miss:+.2f}%"
        if miss_cont_pct is not None:
            line += f"\n    Follow-through: direction held at day 5 in {miss_cont_pct:.0f}% of cases (N={miss_5d_n})"
        ce_lines.append(line)
    if magnitude_trend:
        ce_lines.append(f"  Magnitude trend: {magnitude_trend}")
    ce_section = ""
    if ce_lines:
        ce_section = f"\nCONDITIONAL EARNINGS PROFILE ({hist_sample} quarters):\n" + "\n".join(ce_lines) + "\n"

    # Analyst reaction stats section
    analyst_section = ""
    if analyst_row:
        a_lines = []
        if analyst_row.upgrade_count >= 3 and analyst_row.median_1d_upgrade is not None:
            line = f"  Upgrades (N={analyst_row.upgrade_count}): median 1d move {float(analyst_row.median_1d_upgrade):+.2f}%"
            if analyst_row.upgrade_5d_continuation_pct is not None:
                line += f", 5d continuation {float(analyst_row.upgrade_5d_continuation_pct):.0f}%"
            a_lines.append(line)
        if analyst_row.downgrade_count >= 3 and analyst_row.median_1d_downgrade is not None:
            line = f"  Downgrades (N={analyst_row.downgrade_count}): median 1d move {float(analyst_row.median_1d_downgrade):+.2f}%"
            if analyst_row.downgrade_5d_continuation_pct is not None:
                line += f", 5d continuation {float(analyst_row.downgrade_5d_continuation_pct):.0f}%"
            a_lines.append(line)
        if a_lines:
            analyst_section = "\nANALYST REACTION STATS:\n" + "\n".join(a_lines) + "\n"

    prompt = f"""\
You are a financial data assistant. Your role: translate a user's {direction} view on {sym} into data-grounded thesis parameters. The user has already decided the direction — you calibrate the HOW (target, strike, strategy), not the WHAT.

CRITICAL RULES (violating any is an error):
1. Return ONLY a valid JSON object — no prose before or after it, no markdown fences
2. Every figure in "reasoning" and "strategy" MUST appear verbatim in the fact block below
3. "suggested_strike" MUST be one of the exact float values listed under AVAILABLE STRIKES — never a made-up number
4. "realism_flag" MUST be a non-null string (with specific numbers) whenever the target exceeds the REALISM THRESHOLDS
5. "Aggressive" means ambitious but data-supported. A target beyond historical max moves is a lottery ticket — label it as such with context
6. Frame everything as a data-grounded suggestion to review, not a prediction or advice
7. The "reasoning" MUST cite: (a) the vol regime and its implication for structure choice, (b) at least one historical-reaction or conditional-earnings fact, and (c) analyst-reaction data when available (N≥3)

═══════════════════ INJECTED FACT BLOCK ═══════════════════
SYMBOL / DIRECTION: {sym} / {direction}
CURRENT PRICE:      ${current_price:.2f}
ATM STRIKE:         {f"${atm_strike:.2f}" if atm_strike else "(unavailable)"}
NEXT EARNINGS DATE: {earnings_str or "(unknown)"}
EXPIRATION USED:    {chosen_exp or "(none)"} ({_n(days_to_exp, "d")} days out)

EXPECTED MOVE (ATM straddle):
  Implied move:     {em_display}
  Implied range:    {ir_display}
  Straddle price:   ${_n(expected_move_dollars)} (= call mid + put mid at ATM)

HISTORICAL EARNINGS (1-day reactions, {hist_sample} quarters):
  Avg absolute move:  ±{_n(hist_avg*100 if hist_avg else None)}%
  Max absolute move:  ±{_n(hist_max*100 if hist_max else None)}%
  Min absolute move:  ±{_n(hist_min*100 if hist_min else None)}%
  Beat rate:          {_n(beat_rate)}%
  Beat-but-dropped:   {_n(bbd_rate)}% (price fell after beating this % of the time)
  NOTE: These are 1-day earnings-day reactions; the expiration above covers the full period.
{ce_section}\
VOLATILITY:
  ATM implied vol:    {_pct(atm_iv)}
  20-day realized vol:{_pct(current_rv)}
  RV rank (0–100):    {_n(rv_rank)} (0=1yr low, 100=1yr high)
  IV−RV spread:       {f"{iv_rv_spread_pp:+.1f}pp" if iv_rv_spread_pp is not None else "(unavailable)"}
  Vol regime:         {vol_regime_display}

VOL-REGIME RULES (binding — override aggressiveness defaults when applicable):
  • iv_rich (IV−RV > +8pp): Prefer vertical spreads (bull call spread / bear put spread) to cap premium outlay. Long calls/puts are acceptable ONLY at aggressive level. State in reasoning: "IV is Xpp above RV — using a spread to reduce vol drag."
  • iv_cheap (IV−RV < −4pp): Long calls/puts are attractive — premium is discounted relative to realized movement. State in reasoning: "IV is Xpp below RV — long premium is well-priced."
  • iv_fair (−4pp ≤ IV−RV ≤ +8pp): No vol-regime override — follow the aggressiveness guide as-is.
{analyst_section}\
AVAILABLE STRIKES — {primary_label}:
{primary_text}

AVAILABLE STRIKES — {secondary_label}:
{secondary_text}
═══════════════════ END FACT BLOCK ═══════════════════════

AGGRESSIVENESS REQUESTED: {aggressiveness}

AGGRESSIVENESS GUIDE:
  conservative → target within 0.5–0.8× implied move from current price (${current_price:.2f}); ITM or ATM strike; consider spread to cap premium outlay
  moderate     → target ~1× implied move edge ({t1x_display}); ATM or first OTM strike; long call/put OK unless vol regime says otherwise
  aggressive   → target 1.5–2× implied move ({f"${current_price + 1.5*(expected_move_dollars or 0):.2f}" if direction == "bullish" else f"${current_price - 1.5*(expected_move_dollars or 0):.2f}"}); 2–4 strikes OTM; MUST flag if beyond historical max

REALISM THRESHOLDS (pre-computed — enforce these):
  1× implied move target:      {t1x_display}
  Historical max-move target:  {thmax_display}
  Any target beyond {thmax_display} REQUIRES a non-null realism_flag explaining the data context.
{realism_precheck}\
{extra_prompt_section}\
Return ONLY this JSON object (no other text):
{{
  "suggested_target": <float — price target in dollars, data-grounded>,
  "suggested_strike": <float — MUST be a value from AVAILABLE STRIKES list above>,
  "suggested_spread_strike": <float or null — second leg for spread, else null>,
  "strategy": "<e.g. 'Long $315 call ($5.80 mid)' or 'Bull call spread $315/$325 ($X.XX net debit)'>",
  "reasoning": "<2–4 sentences citing specific figures from the fact block>",
  "realism_flag": "<string with specific numbers, or null if target is within data support>"
}}"""

    print(
        f"[thesis-draft] {sym} {direction} {aggressiveness} | "
        f"price=${current_price:.2f} "
        f"em=±{f'{expected_move_pct*100:.1f}%' if expected_move_pct is not None else 'N/A'} "
        f"hist_max=±{f'{hist_max*100:.1f}%' if hist_max is not None else 'N/A'} "
        f"vol_regime={vol_regime or 'N/A'} "
        f"primary_strikes={len(primary_rows)}",
        flush=True,
    )

    # ── 10. Generate ──────────────────────────────────────────────────────────
    client = AnthropicClient()
    try:
        gen = await client.generate_thesis_draft(prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}")

    print(f"[thesis-draft] {sym}: {gen['input_tokens']} in / {gen['output_tokens']} out | raw:\n{gen['content']}", flush=True)

    # ── 11. Parse + validate ──────────────────────────────────────────────────
    try:
        parsed = _extract_json(gen["content"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI returned non-JSON output: {exc}\nRaw: {gen['content'][:300]}")

    suggested_target = parsed.get("suggested_target")
    suggested_strike = parsed.get("suggested_strike")
    spread_strike    = parsed.get("suggested_spread_strike")
    strategy         = parsed.get("strategy")
    reasoning        = parsed.get("reasoning", "")
    realism_flag     = parsed.get("realism_flag")

    suggested_strike, spread_strike = _canonicalize_spread(suggested_strike, spread_strike, direction)

    if suggested_strike is not None and suggested_strike not in valid_primary_strikes:
        note = (
            f"Note: AI suggested strike ${suggested_strike:.2f} was not found in the available chain "
            f"— verify before trading. Valid nearby strikes: "
            f"{', '.join(f'${s:.2f}' for s in sorted(valid_primary_strikes)[:5])}."
        )
        realism_flag = f"{realism_flag} {note}".strip() if realism_flag else note

    return ThesisDraftRead(
        symbol=sym,
        direction=direction,
        aggressiveness=aggressiveness,
        suggested_target=suggested_target,
        suggested_strike=suggested_strike,
        suggested_spread_strike=spread_strike,
        strategy=strategy,
        reasoning=reasoning,
        realism_flag=realism_flag,
        vol_regime=vol_regime,
        fact_block=fact_block,
        model_used=gen["model_used"],
        generated_at=generated_at,
    )


# ── Draft endpoint ─────────────────────────────────────────────────────────────

@router.post("/draft", response_model=ThesisDraftRead, dependencies=[Depends(require_admin)])
async def draft_thesis(
    payload: ThesisDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> ThesisDraftRead:
    """AI-assisted thesis parameter drafting."""
    data = await _gather_draft_data(payload.symbol.upper(), db)
    return await _run_draft_generation(
        data,
        payload.direction.lower(),
        payload.aggressiveness.lower(),
        proposed_target=payload.proposed_target,
    )


# ── Alert-pick endpoint ───────────────────────────────────────────────────────

@router.post("/alert-pick", response_model=AlertPickRead, dependencies=[Depends(require_admin)])
async def alert_pick(
    payload: AlertPickRequest,
    db: AsyncSession = Depends(get_db),
) -> AlertPickRead:
    """Evidence-based auto-direction: compute signal leans, pick direction when
    signals agree (or decline when they conflict), draft at moderate aggressiveness,
    and persist every pick to alert_picks."""
    sym = payload.symbol.upper()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    # ── Duplicate refusal: one open pick per symbol ────────────────────────
    existing = (await db.execute(
        select(AlertPick).where(AlertPick.symbol == sym, AlertPick.status == "open")
        .order_by(AlertPick.generated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if existing:
        return AlertPickRead(
            symbol=existing.symbol,
            picked_direction=existing.picked_direction,
            leans=[SignalLean(**l) for l in existing.leans],
            draft=None,
            generated_at=existing.generated_at.isoformat(),
            existing_pick=True,
        )

    data = await _gather_draft_data(sym, db)

    earnings_str = data["earnings_str"]
    hist_sample = data["hist_sample"]
    beat_rate = data["beat_rate"]
    median_1d_on_beat = data["median_1d_on_beat"]
    median_1d_on_miss = data["median_1d_on_miss"]
    analyst_row = data["analyst_row"]
    ticker_row = data["ticker_row"]
    rv_raw = data["rv_raw"]
    current_price = data["current_price"]
    vol_regime = data["vol_regime"]
    chosen_exp = data["chosen_exp"]

    # ── Earnings lean ────────────────────────────────────────────────────────
    if earnings_str and hist_sample >= 8 and beat_rate is not None:
        med_beat = median_1d_on_beat or 0.0
        med_miss = median_1d_on_miss or 0.0
        br = beat_rate / 100
        weighted = br * med_beat + (1 - br) * med_miss
        if weighted > 0.5:
            earnings_lean = SignalLean(
                signal="earnings", direction="bullish",
                justification=f"Beats {beat_rate:.0f}% of the time (median +{med_beat:.1f}%); weighted expected 1d: {weighted:+.1f}%",
            )
        elif weighted < -0.5:
            earnings_lean = SignalLean(
                signal="earnings", direction="bearish",
                justification=f"Weighted expected 1d: {weighted:+.1f}% (beat rate {beat_rate:.0f}%, median on beat {med_beat:+.1f}%, on miss {med_miss:+.1f}%)",
            )
        else:
            earnings_lean = SignalLean(
                signal="earnings", direction="neutral",
                justification=f"Weighted expected 1d near zero ({weighted:+.1f}%); no clear earnings edge",
            )
    else:
        earnings_lean = SignalLean(
            signal="earnings", direction="neutral",
            justification="No upcoming earnings or insufficient history",
        )

    # ── Analyst lean ─────────────────────────────────────────────────────────
    today = date.today()
    cutoff = today - timedelta(days=90)
    recent_actions = (await db.execute(
        select(Event).where(
            Event.ticker_id == ticker_row.id,
            Event.event_type == EventType.ANALYST_ACTION,
            Event.event_date >= cutoff,
        )
    )).scalars().all()
    recent_ups = sum(1 for e in recent_actions if e.metadata_.get("action") == "up")
    recent_downs = sum(1 for e in recent_actions if e.metadata_.get("action") == "down")

    if recent_ups + recent_downs < 3:
        analyst_lean = SignalLean(
            signal="analyst", direction="neutral",
            justification=f"Only {recent_ups + recent_downs} analyst actions in 90 days; insufficient",
        )
    elif recent_ups > recent_downs:
        med_str = f", upgrades historically lift {float(analyst_row.median_1d_upgrade):+.1f}% median" if analyst_row and analyst_row.median_1d_upgrade else ""
        analyst_lean = SignalLean(
            signal="analyst", direction="bullish",
            justification=f"{recent_ups} upgrades vs {recent_downs} downgrades in 90 days{med_str}",
        )
    elif recent_downs > recent_ups:
        med_str = f", downgrades historically hit {float(analyst_row.median_1d_downgrade):+.1f}% median" if analyst_row and analyst_row.median_1d_downgrade else ""
        analyst_lean = SignalLean(
            signal="analyst", direction="bearish",
            justification=f"{recent_downs} downgrades vs {recent_ups} upgrades in 90 days{med_str}",
        )
    else:
        analyst_lean = SignalLean(
            signal="analyst", direction="neutral",
            justification=f"Evenly split: {recent_ups} upgrades, {recent_downs} downgrades in 90 days",
        )

    # ── Momentum lean ────────────────────────────────────────────────────────
    pct_20d = rv_raw.get("pct_change_20d")
    if pct_20d is None:
        momentum_lean = SignalLean(
            signal="momentum", direction="neutral",
            justification="Price data unavailable",
        )
    elif pct_20d > 5:
        momentum_lean = SignalLean(
            signal="momentum", direction="bullish",
            justification=f"Up {pct_20d:+.1f}% over 20 trading days",
        )
    elif pct_20d < -5:
        momentum_lean = SignalLean(
            signal="momentum", direction="bearish",
            justification=f"Down {pct_20d:+.1f}% over 20 trading days",
        )
    else:
        momentum_lean = SignalLean(
            signal="momentum", direction="neutral",
            justification=f"Flat ({pct_20d:+.1f}% over 20 days); no clear trend",
        )

    # ── Decision rule ────────────────────────────────────────────────────────
    leans = [earnings_lean, analyst_lean, momentum_lean]
    bullish_count = sum(1 for l in leans if l.direction == "bullish")
    bearish_count = sum(1 for l in leans if l.direction == "bearish")

    if bullish_count >= 2 and bearish_count == 0:
        picked_direction = "bullish"
    elif bearish_count >= 2 and bullish_count == 0:
        picked_direction = "bearish"
    else:
        picked_direction = "mixed_evidence"

    print(
        f"[alert-pick] {sym} | earnings={earnings_lean.direction} analyst={analyst_lean.direction} "
        f"momentum={momentum_lean.direction} → {picked_direction}",
        flush=True,
    )

    # ── On clear direction: run draft engine ─────────────────────────────────
    draft_read: ThesisDraftRead | None = None
    if picked_direction != "mixed_evidence":
        lean_lines = "\n".join(
            f"  - {l.signal}: {l.direction} — {l.justification}" for l in leans
        )
        extra_prompt = (
            f"\nALERT-PICK MODE:\n"
            f"Alert selected {picked_direction} based on the following signal analysis:\n"
            f"{lean_lines}\n"
            f"In your reasoning, explicitly state which signals drove this direction choice.\n"
        )
        draft_read = await _run_draft_generation(
            data, picked_direction, "moderate", extra_prompt_section=extra_prompt,
        )

        # ── Persist to alert_picks ───────────────────────────────────────────
        primary_rows = draft_read.fact_block.get("primary_strikes", [])
        secondary_rows = draft_read.fact_block.get("secondary_strikes", [])
        suggested_strike = draft_read.suggested_strike
        spread_strike = draft_read.suggested_spread_strike

        leg1_mid = next((s["mid"] for s in primary_rows if s["strike"] == suggested_strike), None) if suggested_strike else None
        # Vertical spreads: both legs are same side (both calls or both puts) → check primary_rows first
        leg2_mid = next((s["mid"] for s in primary_rows if s["strike"] == spread_strike), None) if spread_strike else None
        if leg2_mid is None and spread_strike:
            leg2_mid = next((s["mid"] for s in secondary_rows if s["strike"] == spread_strike), None)

        if spread_strike and leg1_mid and leg2_mid:
            cost_to_enter = round(leg1_mid - leg2_mid, 4)
            spread_width = abs(suggested_strike - spread_strike)
            max_loss = round(cost_to_enter * 100, 2)
            max_gain = round((spread_width - cost_to_enter) * 100, 2)
        elif leg1_mid:
            cost_to_enter = leg1_mid
            max_loss = round(leg1_mid * 100, 2)
            max_gain = None  # unlimited for single leg
        else:
            cost_to_enter = None
            max_loss = None
            max_gain = None

        pick = AlertPick(
            symbol=sym,
            picked_direction=picked_direction,
            leans=[l.model_dump() for l in leans],
            strategy=draft_read.strategy,
            suggested_strike=suggested_strike,
            suggested_spread_strike=spread_strike,
            suggested_target=draft_read.suggested_target,
            expiration=chosen_exp,
            cost_to_enter=cost_to_enter,
            max_loss=max_loss,
            max_gain=max_gain,
            vol_regime=vol_regime,
            reasoning=draft_read.reasoning,
            entry_price=current_price,
        )
        db.add(pick)
        await db.commit()

    return AlertPickRead(
        symbol=sym,
        picked_direction=picked_direction,
        leans=leans,
        draft=draft_read,
        generated_at=generated_at,
    )



# ── Alert-picks ledger ─────────────────────────────────────────────────────────

@router.get("/alert-picks", response_model=list[AlertPickLedgerItem], dependencies=[Depends(require_admin)])
async def list_alert_picks(
    db: AsyncSession = Depends(get_db),
) -> list[AlertPickLedgerItem]:
    """List all alert picks newest-first, with live price marks."""
    rows = (await db.execute(
        select(AlertPick).order_by(AlertPick.generated_at.desc())
    )).scalars().all()

    if not rows:
        return []

    # Fetch live prices for all symbols in one batch
    symbols = list({r.symbol for r in rows})
    finnhub = FinnhubClient()
    try:
        raw_quotes = await asyncio.gather(
            *(finnhub.get_quote(s) for s in symbols),
            return_exceptions=True,
        )
    finally:
        await finnhub.close()

    price_map: dict[str, float | None] = {}
    for sym, q in zip(symbols, raw_quotes):
        if isinstance(q, BaseException):
            price_map[sym] = None
        else:
            price_map[sym] = float(q.get("c") or 0) or None

    items = []
    for r in rows:
        entry = float(r.entry_price)
        current = price_map.get(r.symbol)
        unrealized = round(((current - entry) / entry) * 100, 2) if current and entry else None

        items.append(AlertPickLedgerItem(
            id=str(r.id),
            symbol=r.symbol,
            picked_direction=r.picked_direction,
            strategy=r.strategy,
            suggested_strike=float(r.suggested_strike) if r.suggested_strike else None,
            suggested_spread_strike=float(r.suggested_spread_strike) if r.suggested_spread_strike else None,
            suggested_target=float(r.suggested_target) if r.suggested_target else None,
            expiration=r.expiration,
            entry_price=entry,
            current_price=current,
            unrealized_move_pct=unrealized,
            cost_to_enter=float(r.cost_to_enter) if r.cost_to_enter else None,
            max_loss=float(r.max_loss) if r.max_loss else None,
            max_gain=float(r.max_gain) if r.max_gain else None,
            vol_regime=r.vol_regime,
            algo_version=r.algo_version,
            leans=[SignalLean(**l) for l in r.leans],
            reasoning=r.reasoning,
            generated_at=r.generated_at.isoformat(),
            status=r.status,
        ))

    return items


# ── Budget-constrained alternative endpoint ────────────────────────────────────

@router.post("/draft-alternative", response_model=ThesisDraftAlternativeRead, dependencies=[Depends(require_admin)])
async def draft_alternative(
    payload: ThesisDraftAlternativeRequest,
    db: AsyncSession = Depends(get_db),
) -> ThesisDraftAlternativeRead:
    """Generate a budget-constrained alternative to the best trade draft.

    Reuses market-data gather + chain fetch + _build_strike_lines.
    Returns fits=False (never crashes) when:
      - no liquid options exist for the symbol
      - only lottery-ticket far-OTM plays fit the budget
      - AI returns invalid strikes or cost above budget (validation failure)
    The existing /theses/draft endpoint and its output are never touched.
    """
    sym = payload.symbol.upper()
    direction = payload.direction.lower()
    aggressiveness = payload.aggressiveness.lower()
    budget = payload.budget
    loop = asyncio.get_event_loop()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    # ── 1. Parallel market data fetch ─────────────────────────────────────────
    finnhub = FinnhubClient()
    try:
        quote, expirations = await asyncio.gather(
            finnhub.get_quote(sym),
            loop.run_in_executor(None, YFinanceClient.get_option_expirations, sym),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {exc}")
    finally:
        await finnhub.close()

    current_price: float | None = float(quote.get("c") or 0) or None
    if not current_price:
        raise HTTPException(status_code=422, detail=f"No live price available for {sym}")

    # ── 2. DB: ticker + next earnings ─────────────────────────────────────────
    ticker_row = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    if not ticker_row:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    today = date.today()
    ned_val = (await db.execute(
        select(func.min(Event.event_date))
        .where(Event.event_type == "earnings", Event.event_date >= today,
               Event.ticker_id == ticker_row.id)
    )).scalar_one_or_none()
    earnings_str: str | None = (
        ned_val.isoformat() if ned_val and hasattr(ned_val, "isoformat") else (str(ned_val) if ned_val else None)
    )

    # ── 3. Choose expiration (same logic as draft_thesis) ─────────────────────
    chosen_exp: str | None = None
    if expirations:
        if earnings_str:
            post = [e for e in expirations if e >= earnings_str]
            chosen_exp = post[0] if post else expirations[-1]
        else:
            week_out = (today + timedelta(days=7)).isoformat()
            chosen_exp = next((e for e in expirations if e >= week_out), expirations[0])

    # ── 4. Options chain ──────────────────────────────────────────────────────
    chain: dict = {"calls": [], "puts": []}
    if chosen_exp:
        chain = await loop.run_in_executor(None, YFinanceClient.get_option_chain, sym, chosen_exp)

    calls_raw: list[dict] = chain.get("calls", [])
    puts_raw:  list[dict] = chain.get("puts",  [])

    # ── 5. ATM strike ─────────────────────────────────────────────────────────
    atm_strike: float | None = None
    intersection = {c["strike"] for c in calls_raw} & {p["strike"] for p in puts_raw}
    if intersection:
        atm_strike = min(intersection, key=lambda s: abs(s - current_price))

    # ── 6. Quality-filtered strike lists ──────────────────────────────────────
    if direction == "bullish":
        primary_raw, secondary_raw = calls_raw, puts_raw
        primary_label   = "CALLS (for bullish position)"
        secondary_label = "PUTS (for spread second leg)"
    else:
        primary_raw, secondary_raw = puts_raw, calls_raw
        primary_label   = "PUTS (for bearish position)"
        secondary_label = "CALLS (for spread second leg)"

    primary_text,   primary_rows   = _build_strike_lines(primary_raw,   atm_strike, current_price)
    secondary_text, secondary_rows = _build_strike_lines(secondary_raw, atm_strike, current_price, limit=8)

    valid_primary_strikes = {r["strike"] for r in primary_rows}

    # ── NVR / no-options early exit ───────────────────────────────────────────
    if not primary_rows:
        return ThesisDraftAlternativeRead(
            fits=False,
            strategy=None, suggested_strike=None, suggested_spread_strike=None,
            cost_to_enter=None, target=None, tradeoff=None, reasoning=None,
            note=f"No liquid options found for {sym} — no alternative structure can be constructed.",
            model_used="n/a",
            generated_at=generated_at,
        )

    # ── 7. Build prompt ───────────────────────────────────────────────────────
    if payload.best_spread_strike is not None:
        best_play_desc = f"${payload.best_strike:.2f}/${payload.best_spread_strike:.2f} {direction} spread"
    else:
        best_play_desc = f"${payload.best_strike:.2f} {direction} option"

    prompt = f"""\
You are a financial data assistant. The user wants a {direction} trade on {sym} but their budget of ${budget:.0f} per contract is below the best play's cost of ${payload.best_cost:.0f} ({best_play_desc}). Find a REAL cheaper alternative from the available strikes, OR honestly report that nothing good fits within the budget.

CRITICAL RULES (violating any is an error):
1. Output ONLY the JSON object. Do not write any reasoning, explanation, or "thinking out loud" text before the JSON. Your response must begin with {{ and end with }}.
2. You may and should verify your arithmetic, but show any necessary math compactly INSIDE the JSON fields (e.g. in "tradeoff": "Caps max gain at $253 ([$5.00 width − $2.47 debit] × 100)"), NOT as prose before the JSON object.
3. "suggested_strike" and "suggested_spread_strike" MUST be exact float values listed under AVAILABLE STRIKES — never invent a strike
4. "cost_to_enter" MUST be <= {budget:.2f} when fits=true. Naked cost = premium × 100; spread cost = net_debit × 100 where net_debit = leg1_mid − leg2_mid
5. HONESTY GUARDRAIL: If every structure that fits the budget is far-OTM (more than 3 strikes from ATM) or costs less than $50 per contract for this underlying, it is a lottery ticket. Set fits=false and explain honestly. It is better to report nothing fits than to suggest a low-probability play
6. Frame as a data-grounded suggestion to review — not financial advice

═══════════════════ INJECTED FACT BLOCK ═══════════════════
SYMBOL / DIRECTION: {sym} / {direction}
CURRENT PRICE:      ${current_price:.2f}
ATM STRIKE:         {f"${atm_strike:.2f}" if atm_strike else "(unavailable)"}
EXPIRATION:         {chosen_exp or "(none)"}
NEXT EARNINGS:      {earnings_str or "(unknown)"}
AGGRESSIVENESS:     {aggressiveness}
USER BUDGET:        ${budget:.2f} per contract (hard ceiling — must not exceed)

BEST PLAY (context only — do NOT suggest this):
  Structure: {best_play_desc}
  Cost:      ${payload.best_cost:.0f} per contract — exceeds user budget

AVAILABLE STRIKES — {primary_label}:
{primary_text}

AVAILABLE STRIKES — {secondary_label}:
{secondary_text}
═══════════════════ END FACT BLOCK ═══════════════════════

SEARCH ORDER FOR ALTERNATIVES (prefer in this order):
  1. A tighter spread using real strikes where net_debit × 100 <= {budget:.0f}
  2. A further-OTM naked option (1-2 strikes OTM from ATM) where mid × 100 <= {budget:.0f}
  3. fits=false — if nothing affordable is within 3 strikes of ATM or if all affordable plays cost < $50, report nothing good fits

When fits=true, "tradeoff" MUST state what is given up vs {best_play_desc} (e.g. "Caps max gain at $X vs unlimited for the naked call" or "Requires a move to $X vs $Y — lower probability of profit").

SPREAD MAX-GAIN MATH — READ THIS CAREFULLY:
  MAX GAIN for a vertical spread = (width − net_debit) × 100.
  Example: $15-wide spread at $6.00 net debit → (15 − 6) × 100 = $900. The max gain is $900, NOT $1,500.
  $1,500 is the gross spread width × 100 — that figure is WRONG as max gain and must NEVER appear as the max gain.
  The single max-gain dollar figure you state in "tradeoff" MUST equal (width − net_debit) × 100. State that one number only.
  SANITY CHECK before you write the tradeoff: does your stated max gain equal (width − net_debit) × 100?
  If you wrote width × 100 anywhere as the max gain, it is wrong — recompute before responding.

Return ONLY this JSON object (no other text):
{{
  "fits": <true|false>,
  "strategy": "<description with real strikes and real cost, e.g. 'Bull call spread $305/$320 ($8.10 net debit)' — or null if fits=false>",
  "suggested_strike": <float — must appear verbatim in AVAILABLE STRIKES, or null if fits=false>,
  "suggested_spread_strike": <float from AVAILABLE STRIKES or null>,
  "cost_to_enter": <float, must be <= {budget:.2f} if fits=true, else null>,
  "target": <float — data-grounded price target at {aggressiveness} aggressiveness>,
  "tradeoff": "<honest comparison to best play — null if fits=false>",
  "reasoning": "<2-3 sentences citing real strike values and mids from the fact block — null if fits=false>",
  "note": "<when fits=false: specific reason nothing fits + recommendation (try larger budget or lower-priced underlying); null when fits=true>"
}}"""

    print(
        f"[draft-alternative] {sym} {direction} {aggressiveness} | "
        f"budget=${budget:.0f} best_cost=${payload.best_cost:.0f} "
        f"primary_strikes={len(primary_rows)}",
        flush=True,
    )

    # ── 8. Generate ───────────────────────────────────────────────────────────
    client = AnthropicClient()
    try:
        gen = await client.generate_thesis_draft_alternative(prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}")

    print(
        f"[draft-alternative] {sym}: {gen['input_tokens']} in / {gen['output_tokens']} out | raw:\n{gen['content']}",
        flush=True,
    )

    # ── 9. Parse ──────────────────────────────────────────────────────────────
    try:
        parsed = _extract_json(gen["content"])
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI returned non-JSON output: {exc}\nRaw: {gen['content'][:300]}",
        )

    fits              = bool(parsed.get("fits", False))
    strategy          = parsed.get("strategy")
    suggested_strike  = parsed.get("suggested_strike")
    spread_strike     = parsed.get("suggested_spread_strike")
    cost_to_enter     = parsed.get("cost_to_enter")  # AI value; overridden below from chain mids
    target            = parsed.get("target")
    tradeoff          = parsed.get("tradeoff")
    reasoning         = parsed.get("reasoning")
    note              = parsed.get("note")

    # Canonicalize leg order: suggested_strike is always the long leg.
    suggested_strike, spread_strike = _canonicalize_spread(suggested_strike, spread_strike, direction)

    # Override cost_to_enter with Python-computed value from chain mids — never trust the AI's figure.
    # primary_rows is already in scope: list of {"strike": float, "mid": float, "iv": ...}
    if fits and suggested_strike is not None:
        def _find_mid(k: float) -> float | None:
            row = next((r for r in primary_rows if abs(r["strike"] - k) < 1e-6), None)
            return row["mid"] if row else None

        long_mid = _find_mid(suggested_strike)
        if long_mid is None:
            cost_to_enter = None
        elif spread_strike is not None:
            short_mid = _find_mid(spread_strike)
            if short_mid is None:
                cost_to_enter = None
            else:
                cost_to_enter = round((long_mid - short_mid) * 100, 2)
        else:
            cost_to_enter = round(long_mid * 100, 2)

    # ── 10. Validate — prefer fits=false over returning bad data ──────────────
    if fits:
        failures: list[str] = []

        if suggested_strike is None:
            failures.append("fits=true but no suggested_strike returned")
        elif suggested_strike not in valid_primary_strikes:
            failures.append(
                f"strike ${suggested_strike:.2f} not in available chain "
                f"(valid: {', '.join(f'${s:.2f}' for s in sorted(valid_primary_strikes)[:5])})"
            )

        if spread_strike is not None and spread_strike not in valid_primary_strikes:
            failures.append(f"spread strike ${spread_strike:.2f} not in available chain")

        if cost_to_enter is None:
            failures.append("fits=true but cost_to_enter could not be computed — strike mid not found in chain")
        elif cost_to_enter > budget:
            failures.append(
                f"cost_to_enter ${cost_to_enter:.2f} exceeds budget ${budget:.2f}"
            )

        if failures:
            fits              = False
            strategy          = None
            suggested_strike  = None
            spread_strike     = None
            cost_to_enter     = None
            tradeoff          = None
            reasoning         = None
            note = "Alternative validation failed: " + "; ".join(failures) + ". No reliable alternative could be confirmed within budget."

    return ThesisDraftAlternativeRead(
        fits=fits,
        strategy=strategy,
        suggested_strike=suggested_strike,
        suggested_spread_strike=spread_strike,
        cost_to_enter=cost_to_enter,
        target=target,
        tradeoff=tradeoff,
        reasoning=reasoning,
        note=note,
        model_used=gen["model_used"],
        generated_at=generated_at,
    )


# ── CRUD routes ────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[ThesisRead])
async def list_theses(
    symbol: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[ThesisRead]:
    q = (
        select(Thesis)
        .options(selectinload(Thesis.ticker))
        .order_by(Thesis.created_at.desc())
    )
    if symbol:
        ticker_sq = select(Ticker.id).where(Ticker.symbol == symbol.upper()).scalar_subquery()
        q = q.where(Thesis.ticker_id == ticker_sq)
    if status_filter:
        q = q.where(Thesis.status == status_filter)
    result = await db.execute(q)
    return [_to_read(t) for t in result.scalars().all()]


@router.post("/", response_model=ThesisRead, status_code=status.HTTP_201_CREATED)
async def create_thesis(
    payload: ThesisCreate,
    db: AsyncSession = Depends(get_db),
) -> ThesisRead:
    sym = payload.symbol.upper()

    ticker = await db.scalar(select(Ticker).where(Ticker.symbol == sym))
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    loop = asyncio.get_event_loop()

    # ── Capture entry_price from live quote ───────────────────────────────────
    entry_price: float | None = None
    finnhub = FinnhubClient()
    try:
        quote = await finnhub.get_quote(sym)
        p = quote.get("c")
        if p and float(p) > 0:
            entry_price = float(p)
    except Exception:
        pass
    finally:
        await finnhub.close()

    # ── Capture entry_premium from live chain (if option leg specified) ───────
    entry_premium: float | None = None
    entry_premium2: float | None = None

    if payload.option_type and payload.strike and payload.option_expiration:
        try:
            chain = await loop.run_in_executor(
                None, YFinanceClient.get_option_chain, sym, payload.option_expiration
            )
            side = chain.get("calls") if payload.option_type == "call" else chain.get("puts", [])
            c1 = next((c for c in side if c["strike"] == float(payload.strike)), None) if side else None
            if c1:
                entry_premium = _mid_or_last(c1.get("bid"), c1.get("ask"), c1.get("lastPrice"))
            if payload.strike2 is not None:
                c2 = next((c for c in side if c["strike"] == float(payload.strike2)), None) if side else None
                if c2:
                    entry_premium2 = _mid_or_last(c2.get("bid"), c2.get("ask"), c2.get("lastPrice"))
        except Exception:
            pass  # graceful: thesis created without option premium

    opt_exp = date.fromisoformat(payload.option_expiration) if payload.option_expiration else None

    thesis = Thesis(
        ticker_id=ticker.id,
        direction=payload.direction,
        conviction=payload.conviction,
        catalyst=payload.catalyst,
        price_target=payload.price_target,
        target_date=payload.target_date,
        entry_price=entry_price,
        reasoning=payload.reasoning,
        notes=payload.notes,
        status=ThesisStatus.OPEN,
        option_type=payload.option_type,
        strike=payload.strike,
        option_expiration=opt_exp,
        entry_premium=entry_premium,
        contracts=payload.contracts,
        strike2=payload.strike2,
        entry_premium2=entry_premium2,
        spread_type=payload.spread_type,
        from_ai_draft=payload.from_ai_draft,
    )
    db.add(thesis)
    await db.commit()

    result = await db.execute(
        select(Thesis).options(selectinload(Thesis.ticker)).where(Thesis.id == thesis.id)
    )
    return _to_read(result.scalar_one())


@router.get("/{thesis_id}/mark", response_model=ThesisMarkRead)
async def mark_thesis(thesis_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ThesisMarkRead:
    """Compute live mark-to-market P&L for a thesis's option leg."""
    result = await db.execute(
        select(Thesis).options(selectinload(Thesis.ticker)).where(Thesis.id == thesis_id)
    )
    thesis = result.scalar_one_or_none()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")

    loop = asyncio.get_event_loop()
    return await _compute_option_mark(thesis, loop)


@router.get("/{thesis_id}/stock-mark", response_model=ThesisStockMarkRead)
async def stock_mark_thesis(
    thesis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ThesisStockMarkRead:
    """Compute live price mark for a stock-only thesis (no option leg).

    Marks against the live Finnhub quote — never the options chain.

    If the thesis is past its target_date and still open, auto-resolves it in
    the same request using the live price.  Sets status to RESOLVED (with
    target_reached and direction_correct) or NEEDS_MANUAL_RESOLUTION if the
    price fetch fails.  The frontend should refresh the thesis list when
    auto_resolved is True.

    Returns 400 for option theses — those use GET /mark instead.
    """
    result = await db.execute(
        select(Thesis).options(selectinload(Thesis.ticker)).where(Thesis.id == thesis_id)
    )
    thesis = result.scalar_one_or_none()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    if thesis.option_type:
        raise HTTPException(
            status_code=400,
            detail="This thesis has an option leg — use GET /theses/{id}/mark instead.",
        )

    sym   = thesis.ticker.symbol
    as_of = datetime.now(tz=timezone.utc).isoformat()

    # ── Fetch live stock price (separate from option chain) ────────────────────
    current_price: float | None = None
    finnhub = FinnhubClient()
    try:
        quote = await finnhub.get_quote(sym)
        p = quote.get("c")
        if p and float(p) > 0:
            current_price = float(p)
    except Exception:
        pass
    finally:
        await finnhub.close()

    entry  = float(thesis.entry_price)  if thesis.entry_price  else None
    target = float(thesis.price_target) if thesis.price_target else None

    # ── Compute price progress metrics ─────────────────────────────────────────
    pct_from_entry: float | None = None
    pct_to_target:  float | None = None
    verdict:        str | None   = None

    if current_price is not None and entry is not None:
        pct_from_entry = (current_price - entry) / entry * 100

        # pct_to_target: fraction of the way from entry to target (signed).
        # Negative means moving in the wrong direction.
        if target is not None and target != entry:
            pct_to_target = (current_price - entry) / (target - entry) * 100

        direction = thesis.direction
        if direction == "bullish":
            if target is not None and current_price >= target:
                verdict = "target_hit"
            elif current_price >= entry:   # flat at entry counts as "on track" (not yet reversed)
                verdict = "on_track"
            else:
                verdict = "reversed"
        elif direction == "bearish":
            if target is not None and current_price <= target:
                verdict = "target_hit"
            elif current_price <= entry:   # flat at entry counts as "on track"
                verdict = "on_track"
            else:
                verdict = "reversed"
        # neutral: no directional verdict

    # ── Auto-resolve if past target_date and still open ────────────────────────
    auto_resolved = False
    if thesis.status == ThesisStatus.OPEN and thesis.target_date < date.today():
        if current_price is not None and entry is not None:
            direction_correct: bool | None = None
            target_reached:    bool | None = None

            direction = thesis.direction
            if direction == "bullish":
                direction_correct = current_price > entry
                target_reached    = bool(target is not None and current_price >= target)
            elif direction == "bearish":
                direction_correct = current_price < entry
                target_reached    = bool(target is not None and current_price <= target)
            else:  # neutral — stayed within ±5%
                pct_chg           = abs(current_price - entry) / entry if entry else 0
                direction_correct = pct_chg <= 0.05
                target_reached    = (
                    bool(target is not None and abs(current_price - entry) <= abs(target - entry))
                )

            thesis.status              = ThesisStatus.RESOLVED
            thesis.resolved_at         = datetime.now(timezone.utc)
            thesis.price_at_resolution = current_price   # SQLAlchemy converts float → Numeric
            thesis.direction_correct   = direction_correct
            thesis.target_reached      = target_reached
            await db.commit()
            auto_resolved = True
        else:
            # Price unavailable — flag for manual resolution so the user can
            # enter the final price themselves via the resolve form.
            thesis.status = ThesisStatus.NEEDS_MANUAL_RESOLUTION
            await db.commit()
            auto_resolved = True

    return ThesisStockMarkRead(
        thesis_id=thesis.id,
        current_price=current_price,
        entry_price=entry,
        price_target=target,
        pct_from_entry=round(pct_from_entry, 2) if pct_from_entry is not None else None,
        pct_to_target=round(pct_to_target,  1) if pct_to_target  is not None else None,
        verdict=verdict,
        direction=thesis.direction,
        as_of=as_of,
        auto_resolved=auto_resolved,
    )


@router.get("/{thesis_id}", response_model=ThesisRead)
async def get_thesis(thesis_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ThesisRead:
    result = await db.execute(
        select(Thesis).options(selectinload(Thesis.ticker)).where(Thesis.id == thesis_id)
    )
    thesis = result.scalar_one_or_none()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return _to_read(thesis)


@router.post("/{thesis_id}/resolve", response_model=ThesisRead)
async def resolve_thesis(
    thesis_id: uuid.UUID,
    payload: ThesisResolve,
    db: AsyncSession = Depends(get_db),
) -> ThesisRead:
    result = await db.execute(
        select(Thesis).options(selectinload(Thesis.ticker)).where(Thesis.id == thesis_id)
    )
    thesis = result.scalar_one_or_none()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    if thesis.status == ThesisStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Thesis is already resolved")

    resolution_price: float | None = None
    needs_manual = False

    if payload.price_override is not None:
        resolution_price = float(payload.price_override)
    else:
        finnhub = FinnhubClient()
        try:
            quote = await finnhub.get_quote(thesis.ticker.symbol)
            p = quote.get("c")
            if p and float(p) > 0:
                resolution_price = float(p)
        except Exception:
            pass
        finally:
            await finnhub.close()

    if resolution_price is None:
        needs_manual = True

    direction_correct: bool | None = None
    target_reached: bool | None = None

    if resolution_price is not None and thesis.entry_price is not None:
        entry     = float(thesis.entry_price)
        direction = thesis.direction

        if direction == "bullish":
            direction_correct = resolution_price > entry
        elif direction == "bearish":
            direction_correct = resolution_price < entry
        else:  # neutral — stayed within ±5%
            pct_change = abs(resolution_price - entry) / entry if entry else 0
            direction_correct = pct_change <= 0.05

        if thesis.price_target is not None:
            target = float(thesis.price_target)
            if direction == "bullish":
                target_reached = resolution_price >= target
            elif direction == "bearish":
                target_reached = resolution_price <= target
            else:
                target_reached = abs(resolution_price - entry) <= abs(target - entry)

    # ── Option P&L at resolution ───────────────────────────────────────────────
    option_pnl_dollars: float | None = None
    option_pnl_pct: float | None = None
    if thesis.option_type:
        loop = asyncio.get_event_loop()
        mark = await _compute_option_mark(thesis, loop, stock_price_override=resolution_price)
        option_pnl_dollars = mark.pnl_dollars
        option_pnl_pct     = mark.pnl_pct

    thesis.price_at_resolution = resolution_price
    thesis.direction_correct   = direction_correct
    thesis.target_reached      = target_reached
    thesis.self_grade          = payload.self_grade
    thesis.reflection          = payload.reflection
    thesis.resolved_at         = datetime.now(timezone.utc)
    thesis.option_pnl_dollars  = option_pnl_dollars
    thesis.option_pnl_pct      = option_pnl_pct
    thesis.status              = ThesisStatus.NEEDS_MANUAL_RESOLUTION if needs_manual else ThesisStatus.RESOLVED

    await db.commit()

    result = await db.execute(
        select(Thesis).options(selectinload(Thesis.ticker)).where(Thesis.id == thesis_id)
    )
    return _to_read(result.scalar_one())


@router.delete("/{thesis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thesis(thesis_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    thesis = await db.get(Thesis, thesis_id)
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    await db.delete(thesis)
    await db.commit()
