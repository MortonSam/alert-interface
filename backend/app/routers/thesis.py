import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.enums import EarningsOutcome
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.thesis import Thesis, ThesisStatus
from app.models.ticker import Ticker
from app.schemas.thesis import (
    ThesisCreate,
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


# ── Draft endpoint ─────────────────────────────────────────────────────────────

@router.post("/draft", response_model=ThesisDraftRead)
async def draft_thesis(
    payload: ThesisDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> ThesisDraftRead:
    """AI-assisted thesis parameter drafting.

    Gathers current price, expected move, options chain, historical reactions, and RV.
    Injects these as authoritative facts into a strict prompt; the model synthesises
    realistic targets / strikes / strategy — it never invents numbers.
    """
    sym = payload.symbol.upper()
    direction = payload.direction.lower()
    aggressiveness = payload.aggressiveness.lower()
    loop = asyncio.get_event_loop()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

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

    # pct_change_1d stored as full pct (e.g. 2.77 = 2.77%) — convert to decimal for internal math
    abs_moves_dec = [abs(float(r.pct_change_1d)) / 100 for r in reactions]
    hist_avg: float | None = mean(abs_moves_dec) if abs_moves_dec else None
    hist_max: float | None = max(abs_moves_dec) if abs_moves_dec else None
    hist_min: float | None = min(abs_moves_dec) if abs_moves_dec else None
    hist_sample: int = len(abs_moves_dec)

    beats = [r for r in reactions if r.outcome == EarningsOutcome.BEAT]
    beat_rate: float | None = len(beats) / len(reactions) * 100 if reactions else None
    beat_drops = [r for r in beats if float(r.pct_change_1d) < 0]
    bbd_rate: float | None = len(beat_drops) / len(beats) * 100 if beats else None

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
    if payload.proposed_target is not None:
        pt = payload.proposed_target
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

    prompt = f"""\
You are a financial data assistant. Your role: translate a user's {direction} view on {sym} into data-grounded thesis parameters. The user has already decided the direction — you calibrate the HOW (target, strike, strategy), not the WHAT.

CRITICAL RULES (violating any is an error):
1. Return ONLY a valid JSON object — no prose before or after it, no markdown fences
2. Every figure in "reasoning" and "strategy" MUST appear verbatim in the fact block below
3. "suggested_strike" MUST be one of the exact float values listed under AVAILABLE STRIKES — never a made-up number
4. "realism_flag" MUST be a non-null string (with specific numbers) whenever the target exceeds the REALISM THRESHOLDS
5. "Aggressive" means ambitious but data-supported. A target beyond historical max moves is a lottery ticket — label it as such with context
6. Frame everything as a data-grounded suggestion to review, not a prediction or advice

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

VOLATILITY:
  ATM implied vol:    {_pct(atm_iv)}
  20-day realized vol:{_pct(current_rv)}
  RV rank (0–100):    {_n(rv_rank)} (0=1yr low, 100=1yr high)
  IV−RV spread:       {f"{iv_rv_spread_pp:+.1f}pp" if iv_rv_spread_pp is not None else "(unavailable)"}

AVAILABLE STRIKES — {primary_label}:
{primary_text}

AVAILABLE STRIKES — {secondary_label}:
{secondary_text}
═══════════════════ END FACT BLOCK ═══════════════════════

AGGRESSIVENESS REQUESTED: {aggressiveness}

AGGRESSIVENESS GUIDE:
  conservative → target within 0.5–0.8× implied move from current price (${current_price:.2f}); ITM or ATM strike; consider spread to cap premium outlay
  moderate     → target ~1× implied move edge ({t1x_display}); ATM or first OTM strike; long call/put OK
  aggressive   → target 1.5–2× implied move ({f"${current_price + 1.5*(expected_move_dollars or 0):.2f}" if direction == "bullish" else f"${current_price - 1.5*(expected_move_dollars or 0):.2f}"}); 2–4 strikes OTM; MUST flag if beyond historical max

REALISM THRESHOLDS (pre-computed — enforce these):
  1× implied move target:      {t1x_display}
  Historical max-move target:  {thmax_display}
  Any target beyond {thmax_display} REQUIRES a non-null realism_flag explaining the data context.
{realism_precheck}
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
        fact_block=fact_block,
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
