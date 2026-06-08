import asyncio
import json
import uuid
from datetime import date, timedelta, timezone
from datetime import datetime as dt_datetime
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.ticker import Ticker
from app.models.historical_reaction import HistoricalReaction
from app.schemas.options import ExpectedMoveRead, HistoricalMoveStats, OptionsChainRead, OptionContractRead, OptionsReadRead, RealizedVolRead, StrategyDataRead, StrikeData
from app.services.anthropic_client import AnthropicClient
from app.services.system_metadata_service import get_value as _get_meta, set_value as _set_meta
from app.schemas.ticker import BatchQuoteRead, EarningsMarker, SparklinePoint, TickerChartRead, TickerCreate, TickerQuoteRead, TickerRead, TickerUpdate
from app.services.finnhub_client import FinnhubClient
from app.services.options_cache import fetch_chain
from app.services import quote_cache
from app.services.yfinance_client import YFinanceClient

router = APIRouter(prefix="/tickers", tags=["tickers"])


def _build_plain_summary(
    symbol: str,
    expected_move_pct: float | None,
    implied_range_low: float | None,
    implied_range_high: float | None,
    expiration_used: str | None,
    earnings_date: str | None,
    days_expiration_past_earnings: int | None,
    historical_stats: HistoricalMoveStats | None,
) -> str | None:
    if expected_move_pct is None or expiration_used is None:
        return None

    pct_str = f"±{expected_move_pct * 100:.1f}%"

    # Base sentence
    if implied_range_low is not None and implied_range_high is not None:
        base = (
            f"{symbol} options are pricing in a {pct_str} move "
            f"(${implied_range_low:.2f}–${implied_range_high:.2f}) by {expiration_used}."
        )
    else:
        base = f"{symbol} options are pricing in a {pct_str} move by {expiration_used}."

    parts = [base]

    # Earnings clause — only when expiration is within 30 days of earnings
    if (
        earnings_date
        and days_expiration_past_earnings is not None
        and 0 <= days_expiration_past_earnings <= 30
    ):
        parts.append(f"This is partly driven by the {earnings_date} earnings report.")

    # Magnitude vs historical — always honest about window mismatch
    if historical_stats and historical_stats.sample_size >= 3:
        avg = historical_stats.avg_abs_move_pct
        hist_str = f"±{avg * 100:.1f}%"
        max_str = f"±{historical_stats.max_abs_move_pct * 100:.1f}%"

        if days_expiration_past_earnings is not None and days_expiration_past_earnings <= 3:
            # Windows roughly match — direct comparison fair
            ratio = expected_move_pct / avg if avg > 0 else 1.0
            if ratio > 1.25:
                parts.append(
                    f"That's a wider-than-usual range — the historical average 1-day earnings move is {hist_str}."
                )
            elif ratio < 0.80:
                parts.append(
                    f"That's a narrower-than-usual range — the historical average 1-day earnings move is {hist_str}."
                )
            else:
                parts.append(
                    f"That's roughly in line with the historical average 1-day earnings move of {hist_str}."
                )
        else:
            # Mismatched windows — show historical for context but frame honestly
            days_label = (
                f"{days_expiration_past_earnings} days to expiration"
                if days_expiration_past_earnings is not None
                else "multiple weeks to expiration"
            )
            parts.append(
                f"For context, {symbol}'s historical average 1-day earnings move is {hist_str} (max {max_str}), "
                f"but the implied {pct_str} covers {days_label}, not just the earnings day."
            )

    return " ".join(parts)


def _mid_or_last(bid, ask, last):
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return last if last and last > 0 else None


_IV_TRUST_CAP = 1.0  # 100% annualized IV — above this is a calc artifact on normal equities


def _flag_contract(c: dict, current_price: float, is_call: bool) -> str | None:
    """Return a short reason string if a contract looks untrustworthy, else None."""
    bid    = c.get("bid")  or 0.0
    ask    = c.get("ask")  or 0.0
    iv     = c.get("impliedVolatility")
    oi     = c.get("openInterest") or 0
    vol    = c.get("volume")       or 0
    strike = c["strike"]

    # 1. No market at all
    if bid == 0.0 and ask == 0.0:
        return "no_market"

    # 2. IV above sanity cap
    if iv is not None and iv > _IV_TRUST_CAP:
        return "iv_outlier"

    # 3. Bid below intrinsic (arb-free violation — impossible in a real market)
    if bid > 0 and current_price > 0:
        intrinsic = max(0.0, (current_price - strike) if is_call else (strike - current_price))
        if intrinsic > 0 and bid < intrinsic * 0.95:   # 5% tolerance for rounding
            return "below_intrinsic"

    # 4. Bid-ask spread > 50% of mid (no liquid market)
    if bid > 0 and ask > 0:
        mid    = (bid + ask) / 2.0
        spread = ask - bid
        if mid > 0 and spread / mid > 0.50:
            return "wide_spread"

    # 5. Zero OI and zero volume — weakest alone; only flag if IV is also absent/zero
    if oi == 0 and vol == 0 and (iv is None or iv == 0):
        return "no_market"

    return None


def _build_contracts(chain_side, atm_strike, current_price: float | None = None, is_call: bool = False):
    return [OptionContractRead(
        strike=c["strike"], bid=c["bid"], ask=c["ask"], last_price=c["lastPrice"],
        volume=c["volume"], open_interest=c["openInterest"],
        implied_volatility=c["impliedVolatility"],
        is_atm=(atm_strike is not None and c["strike"] == atm_strike),
        data_quality_flag=(
            _flag_contract(c, current_price, is_call)
            if current_price is not None else None
        ),
    ) for c in chain_side]


@router.get("/", response_model=list[TickerRead])
async def list_tickers(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[TickerRead]:
    q = select(Ticker)
    if active_only:
        q = q.where(Ticker.is_active.is_(True))
    result = await db.execute(q.order_by(Ticker.symbol))
    tickers = list(result.scalars().all())

    # One extra query: next upcoming earnings date per ticker
    today = date.today()
    ned_q = (
        select(Event.ticker_id, func.min(Event.event_date).label("ned"))
        .where(Event.event_type == "earnings", Event.event_date >= today)
        .where(Event.ticker_id.isnot(None))
        .group_by(Event.ticker_id)
    )
    ned_rows = await db.execute(ned_q)
    ned_map: dict = {row.ticker_id: row.ned for row in ned_rows}

    enriched: list[TickerRead] = []
    for t in tickers:
        r = TickerRead.model_validate(t)
        r.next_earnings_date = ned_map.get(t.id)
        enriched.append(r)
    return enriched


@router.post("/", response_model=TickerRead, status_code=status.HTTP_201_CREATED)
async def create_ticker(payload: TickerCreate, db: AsyncSession = Depends(get_db)) -> Ticker:
    ticker = Ticker(**payload.model_dump())
    ticker.symbol = ticker.symbol.upper()
    db.add(ticker)
    await db.commit()
    await db.refresh(ticker)
    return ticker


@router.get("/quote/{symbol}", response_model=TickerQuoteRead)
async def get_ticker_quote(symbol: str) -> TickerQuoteRead:
    """Real-time quote (Finnhub) + 30-day daily sparkline (yfinance)."""
    sym = symbol.upper()
    finnhub = FinnhubClient()
    loop = asyncio.get_event_loop()
    try:
        quote, candles = await asyncio.gather(
            finnhub.get_quote(sym),
            # yfinance is sync; run in a thread so we don't block the event loop
            loop.run_in_executor(None, YFinanceClient.get_daily_closes, sym, "1mo"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Quote fetch failed: {exc}")
    finally:
        await finnhub.close()

    def _f(val: object) -> float | None:
        """Float or None; 0.0 from Finnhub means no data (market closed / unknown)."""
        return float(val) if val is not None else None

    return TickerQuoteRead(
        symbol=sym,
        price=_f(quote.get("c")) or None,
        change=_f(quote.get("d")),
        change_pct=_f(quote.get("dp")),
        high=_f(quote.get("h")) or None,
        low=_f(quote.get("l")) or None,
        open=_f(quote.get("o")) or None,
        prev_close=_f(quote.get("pc")) or None,
        timestamp=int(quote["t"]) if quote.get("t") else None,
        sparkline=[SparklinePoint(date=c["date"], close=c["close"]) for c in candles],
    )


@router.get("/quotes", response_model=list[BatchQuoteRead])
async def get_batch_quotes(symbols: str = Query(..., description="Comma-separated symbols")) -> list[BatchQuoteRead]:
    """Batch real-time quotes for the home grid, with 60s per-symbol cache."""
    raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    syms = list(dict.fromkeys(raw))[:50]  # dedupe, cap at 50

    # Partition into cache hits vs misses
    results: dict[str, BatchQuoteRead] = {}
    to_fetch: list[str] = []
    for sym in syms:
        cached = quote_cache.get(sym)
        if cached is not None:
            results[sym] = BatchQuoteRead(symbol=sym, **cached)
        else:
            to_fetch.append(sym)

    # Fetch all misses concurrently via one FinnhubClient
    if to_fetch:
        finnhub = FinnhubClient()
        try:
            raw_quotes = await asyncio.gather(
                *(finnhub.get_quote(s) for s in to_fetch),
                return_exceptions=True,
            )
        finally:
            await finnhub.close()

        for sym, q in zip(to_fetch, raw_quotes):
            if isinstance(q, BaseException):
                results[sym] = BatchQuoteRead(symbol=sym, price=None, change=None, change_pct=None)
                continue
            price = float(q.get("c") or 0) or None
            change = float(q.get("d")) if q.get("d") is not None else None
            change_pct = float(q.get("dp")) if q.get("dp") is not None else None
            data = {"price": price, "change": change, "change_pct": change_pct}
            quote_cache.set(sym, data)
            results[sym] = BatchQuoteRead(symbol=sym, **data)

    return [results.get(s, BatchQuoteRead(symbol=s, price=None, change=None, change_pct=None)) for s in syms]


@router.get("/chart/{symbol}", response_model=TickerChartRead)
async def get_ticker_chart(
    symbol: str,
    period: str = "1y",
    db: AsyncSession = Depends(get_db),
) -> TickerChartRead:
    """Daily (or intraday) price history + earnings markers for the interactive chart."""
    sym = symbol.upper()

    loop = asyncio.get_event_loop()
    chart_result: dict = await loop.run_in_executor(
        None, YFinanceClient.get_chart_history, sym, period
    )
    history_raw: list[dict] = chart_result["history"]
    start_price: float | None = chart_result["start_price"]

    history = [SparklinePoint(date=p["date"], close=p["close"]) for p in history_raw]

    # Date range from history so we only return markers that fall within the window
    if history:
        min_date = history[0].date
    else:
        min_date = "1900-01-01"

    # Fetch ticker + its earnings reactions
    ticker_row = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()

    markers: list[EarningsMarker] = []
    if ticker_row:
        r_q = (
            select(HistoricalReaction)
            .where(
                HistoricalReaction.ticker_id == ticker_row.id,
                HistoricalReaction.event_type == "earnings",
            )
            .order_by(HistoricalReaction.event_date)
        )
        for r in (await db.execute(r_q)).scalars().all():
            if r.event_date.isoformat() >= min_date:
                markers.append(EarningsMarker(
                    date=r.event_date.isoformat(),
                    eps_estimate=float(r.eps_estimate) if r.eps_estimate is not None else None,
                    eps_actual=float(r.eps_actual) if r.eps_actual is not None else None,
                    outcome=r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome),
                    pct_change_1d=float(r.pct_change_1d) if r.pct_change_1d is not None else None,
                    pct_change_3d=float(r.pct_change_3d) if r.pct_change_3d is not None else None,
                    pct_change_5d=float(r.pct_change_5d) if r.pct_change_5d is not None else None,
                ))

    return TickerChartRead(symbol=sym, period=period, history=history, earnings_markers=markers, start_price=start_price)


@router.get("/expected-move/{symbol}", response_model=ExpectedMoveRead)
async def get_expected_move(symbol: str, db: AsyncSession = Depends(get_db)) -> ExpectedMoveRead:
    sym = symbol.upper()
    finnhub = FinnhubClient()
    loop = asyncio.get_event_loop()
    as_of = dt_datetime.now(tz=timezone.utc).isoformat()

    try:
        quote, expirations = await asyncio.gather(
            finnhub.get_quote(sym),
            loop.run_in_executor(None, YFinanceClient.get_option_expirations, sym),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}")
    finally:
        await finnhub.close()

    current_price = float(quote.get("c") or 0) or None

    if not expirations:
        return ExpectedMoveRead(
            symbol=sym, current_price=current_price,
            expected_move_pct=None, expected_move_dollars=None,
            implied_range_low=None, implied_range_high=None,
            expiration_used=None, earnings_date=None,
            days_expiration_past_earnings=None,
            straddle_price=None, atm_strike=None,
            historical_stats=None,
            plain_summary=None,
            data_quality_note="No options expirations available for this symbol.",
            as_of=as_of,
        )

    today = date.today()

    # Look up ticker + next earnings
    ticker_row = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    earnings_str: str | None = None
    if ticker_row:
        ned_q = (
            select(func.min(Event.event_date))
            .where(Event.event_type == "earnings", Event.event_date >= today)
            .where(Event.ticker_id == ticker_row.id)
        )
        ned_result = (await db.execute(ned_q)).scalar_one_or_none()
        if ned_result:
            earnings_str = ned_result.isoformat() if hasattr(ned_result, "isoformat") else str(ned_result)

    data_quality_note: str | None = None
    chosen_exp: str | None = None
    days_expiration_past_earnings: int | None = None

    if earnings_str:
        # Pick the expiration CLOSEST to (but not before) earnings — minimises extra vol
        post_earnings = [e for e in expirations if e >= earnings_str]
        if post_earnings:
            chosen_exp = post_earnings[0]  # expirations are already sorted ascending
        else:
            chosen_exp = expirations[-1]
            data_quality_note = f"No expiration covers earnings date {earnings_str}; using nearest available {chosen_exp}."

        if chosen_exp and earnings_str:
            earnings_date_obj = date.fromisoformat(earnings_str)
            exp_date_obj = date.fromisoformat(chosen_exp)
            days_expiration_past_earnings = (exp_date_obj - earnings_date_obj).days
            if days_expiration_past_earnings > 7 and data_quality_note is None:
                data_quality_note = (
                    f"Nearest available expiration ({chosen_exp}) is "
                    f"{days_expiration_past_earnings} days after the {earnings_str} earnings date. "
                    f"The implied move covers the full period to expiration, not just the earnings event."
                )
    else:
        week_out = (today + timedelta(days=7)).isoformat()
        chosen_exp = next((e for e in expirations if e >= week_out), None)
        if chosen_exp is None:
            chosen_exp = expirations[0]
        data_quality_note = "No earnings date found; using nearest weekly expiration."

    chain_entry = await fetch_chain(sym, chosen_exp, loop)
    chain = chain_entry.chain
    as_of = chain_entry.fetched_at.isoformat()

    calls = chain.get("calls", [])
    puts = chain.get("puts", [])

    call_strikes = {c["strike"] for c in calls}
    put_strikes = {p["strike"] for p in puts}
    intersection = call_strikes & put_strikes

    atm_strike: float | None = None
    straddle_price: float | None = None
    expected_move_pct: float | None = None
    expected_move_dollars: float | None = None
    implied_range_low: float | None = None
    implied_range_high: float | None = None

    if intersection and current_price:
        atm_strike = min(intersection, key=lambda s: abs(s - current_price))
        atm_call = next((c for c in calls if c["strike"] == atm_strike), None)
        atm_put = next((p for p in puts if p["strike"] == atm_strike), None)
        call_price = _mid_or_last(atm_call["bid"], atm_call["ask"], atm_call["lastPrice"]) if atm_call else None
        put_price = _mid_or_last(atm_put["bid"], atm_put["ask"], atm_put["lastPrice"]) if atm_put else None
        if call_price is not None and put_price is not None:
            straddle_price = call_price + put_price
            expected_move_pct = straddle_price / current_price
            expected_move_dollars = straddle_price
            implied_range_low = current_price - straddle_price
            implied_range_high = current_price + straddle_price

    # Historical stats
    historical_stats: HistoricalMoveStats | None = None
    if ticker_row:
        r_q = select(HistoricalReaction).where(
            HistoricalReaction.ticker_id == ticker_row.id,
            HistoricalReaction.event_type == "earnings",
            HistoricalReaction.pct_change_1d.isnot(None),
        )
        reactions = (await db.execute(r_q)).scalars().all()
        if reactions:
            abs_moves = [abs(float(r.pct_change_1d)) / 100 for r in reactions]
            historical_stats = HistoricalMoveStats(
                avg_abs_move_pct=mean(abs_moves),
                max_abs_move_pct=max(abs_moves),
                min_abs_move_pct=min(abs_moves),
                sample_size=len(abs_moves),
                above_expected=sum(1 for m in abs_moves if expected_move_pct is not None and m > expected_move_pct),
                below_expected=sum(1 for m in abs_moves if expected_move_pct is None or m <= expected_move_pct),
            )

    plain_summary = _build_plain_summary(
        symbol=sym,
        expected_move_pct=expected_move_pct,
        implied_range_low=implied_range_low,
        implied_range_high=implied_range_high,
        expiration_used=chosen_exp,
        earnings_date=earnings_str,
        days_expiration_past_earnings=days_expiration_past_earnings,
        historical_stats=historical_stats,
    )

    return ExpectedMoveRead(
        symbol=sym,
        current_price=current_price,
        expected_move_pct=expected_move_pct,
        expected_move_dollars=expected_move_dollars,
        implied_range_low=implied_range_low,
        implied_range_high=implied_range_high,
        expiration_used=chosen_exp,
        earnings_date=earnings_str,
        days_expiration_past_earnings=days_expiration_past_earnings,
        straddle_price=straddle_price,
        atm_strike=atm_strike,
        historical_stats=historical_stats,
        plain_summary=plain_summary,
        data_quality_note=data_quality_note,
        as_of=as_of,
    )


@router.get("/options/{symbol}", response_model=OptionsChainRead)
async def get_options_chain(
    symbol: str,
    expiration: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> OptionsChainRead:
    sym = symbol.upper()
    finnhub = FinnhubClient()
    loop = asyncio.get_event_loop()
    as_of = dt_datetime.now(tz=timezone.utc).isoformat()

    try:
        quote, available = await asyncio.gather(
            finnhub.get_quote(sym),
            loop.run_in_executor(None, YFinanceClient.get_option_expirations, sym),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}")
    finally:
        await finnhub.close()

    current_price = float(quote.get("c") or 0) or None

    if not available:
        return OptionsChainRead(
            symbol=sym, expiration="", current_price=current_price,
            calls=[], puts=[], available_expirations=[], as_of=as_of,
        )

    chosen = expiration if (expiration and expiration in available) else available[0]
    chain_entry = await fetch_chain(sym, chosen, loop)
    chain = chain_entry.chain
    as_of = chain_entry.fetched_at.isoformat()

    calls_raw = chain.get("calls", [])
    puts_raw = chain.get("puts", [])

    all_strikes = sorted({c["strike"] for c in calls_raw} | {p["strike"] for p in puts_raw})
    atm_strike: float | None = None
    if all_strikes and current_price:
        atm_strike = min(all_strikes, key=lambda s: abs(s - current_price))

    def _filter_side(side_raw):
        if not atm_strike:
            return side_raw
        sorted_strikes = sorted({c["strike"] for c in side_raw})
        if atm_strike not in sorted_strikes:
            return side_raw
        atm_idx = sorted_strikes.index(atm_strike)
        keep = set(sorted_strikes[max(0, atm_idx - 15): atm_idx + 16])
        return [c for c in side_raw if c["strike"] in keep]

    filtered_calls = _filter_side(calls_raw)
    filtered_puts = _filter_side(puts_raw)

    return OptionsChainRead(
        symbol=sym,
        expiration=chosen,
        current_price=current_price,
        calls=_build_contracts(filtered_calls, atm_strike, current_price=current_price, is_call=True),
        puts=_build_contracts(filtered_puts,  atm_strike, current_price=current_price, is_call=False),
        available_expirations=available,
        as_of=as_of,
    )


@router.get("/strategy-data/{symbol}", response_model=StrategyDataRead)
async def get_strategy_data(symbol: str, db: AsyncSession = Depends(get_db)) -> StrategyDataRead:
    """Strike-level call/put mid-prices for the earnings-relevant expiration.
    Only returns contracts that pass all quality filters (no wide spread, no_market, etc.)
    so the frontend always works with real, trustworthy premiums.
    """
    sym = symbol.upper()
    finnhub = FinnhubClient()
    loop = asyncio.get_event_loop()
    as_of = dt_datetime.now(tz=timezone.utc).isoformat()

    try:
        quote, expirations = await asyncio.gather(
            finnhub.get_quote(sym),
            loop.run_in_executor(None, YFinanceClient.get_option_expirations, sym),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}")
    finally:
        await finnhub.close()

    current_price = float(quote.get("c") or 0) or None

    if not expirations or not current_price:
        return StrategyDataRead(
            symbol=sym, current_price=current_price, expiration=None,
            implied_range_low=None, implied_range_high=None,
            strikes=[], as_of=as_of,
        )

    today = date.today()

    # Next earnings (same logic as expected-move)
    ticker_row = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    earnings_str: str | None = None
    if ticker_row:
        ned_q = (
            select(func.min(Event.event_date))
            .where(Event.event_type == "earnings", Event.event_date >= today)
            .where(Event.ticker_id == ticker_row.id)
        )
        ned_result = (await db.execute(ned_q)).scalar_one_or_none()
        if ned_result:
            earnings_str = ned_result.isoformat() if hasattr(ned_result, "isoformat") else str(ned_result)

    # Pick expiration
    if earnings_str:
        post = [e for e in expirations if e >= earnings_str]
        chosen_exp: str = post[0] if post else expirations[-1]
    else:
        week_out = (today + timedelta(days=7)).isoformat()
        chosen_exp = next((e for e in expirations if e >= week_out), expirations[0])

    chain_entry = await fetch_chain(sym, chosen_exp, loop)
    chain = chain_entry.chain
    as_of = chain_entry.fetched_at.isoformat()
    calls_raw = chain.get("calls", [])
    puts_raw  = chain.get("puts",  [])

    call_map: dict[float, dict] = {c["strike"]: c for c in calls_raw}
    put_map:  dict[float, dict] = {p["strike"]: p for p in puts_raw}
    all_strike_vals = sorted(call_map.keys() | put_map.keys())

    # ATM and implied range (for overlay)
    atm_strike: float | None = None
    implied_range_low: float | None = None
    implied_range_high: float | None = None
    if all_strike_vals:
        atm_strike = min(all_strike_vals, key=lambda s: abs(s - current_price))
        atm_c = call_map.get(atm_strike)
        atm_p = put_map.get(atm_strike)
        call_price = _mid_or_last(atm_c["bid"], atm_c["ask"], atm_c["lastPrice"]) if atm_c else None
        put_price  = _mid_or_last(atm_p["bid"], atm_p["ask"], atm_p["lastPrice"]) if atm_p else None
        if call_price is not None and put_price is not None:
            straddle = call_price + put_price
            implied_range_low  = current_price - straddle
            implied_range_high = current_price + straddle

    # Build per-strike data — ±35% of current price, only non-flagged mids
    price_lo = current_price * 0.65
    price_hi = current_price * 1.35
    result_strikes: list[StrikeData] = []

    for s in all_strike_vals:
        if not (price_lo <= s <= price_hi):
            continue
        c = call_map.get(s)
        p = put_map.get(s)

        call_mid: float | None = None
        call_iv: float | None = None
        if c and _flag_contract(c, current_price, is_call=True) is None:
            call_mid = _mid_or_last(c["bid"], c["ask"], c["lastPrice"])
            call_iv = c.get("impliedVolatility")  # already cleaned by _parse_option_df

        put_mid: float | None = None
        put_iv: float | None = None
        if p and _flag_contract(p, current_price, is_call=False) is None:
            put_mid = _mid_or_last(p["bid"], p["ask"], p["lastPrice"])
            put_iv = p.get("impliedVolatility")

        if call_mid is None and put_mid is None:
            continue

        result_strikes.append(StrikeData(
            strike=s,
            call_mid=call_mid,
            put_mid=put_mid,
            call_iv=call_iv,
            put_iv=put_iv,
            is_atm=(s == atm_strike),
        ))

    return StrategyDataRead(
        symbol=sym, current_price=current_price, expiration=chosen_exp,
        earnings_date=earnings_str,
        implied_range_low=implied_range_low, implied_range_high=implied_range_high,
        strikes=result_strikes, as_of=as_of,
    )


@router.get("/options-read/{symbol}", response_model=OptionsReadRead)
async def get_options_read(symbol: str, db: AsyncSession = Depends(get_db)) -> OptionsReadRead:
    """AI-generated 2–4 sentence interpretive read synthesizing vol/options data.

    Every number is precomputed server-side and injected as an authoritative string.
    The model narrates; it does not calculate. Cached per calendar day in system_metadata.
    """
    sym = symbol.upper()
    loop = asyncio.get_event_loop()
    today = date.today()
    as_of = dt_datetime.now(tz=timezone.utc).isoformat()
    cache_key = f"options_read:{sym}:{today.isoformat()}"

    # ── Cache check ───────────────────────────────────────────────────────────
    cached_raw = await _get_meta(db, cache_key)
    if cached_raw:
        try:
            c = json.loads(cached_raw)
            return OptionsReadRead(
                symbol=sym, content=c["content"], facts=c["facts"],
                model_used=c["model_used"], generated_at=c["generated_at"],
                cached=True, as_of=as_of,
            )
        except Exception:
            pass  # corrupt cache → fall through to regenerate

    # ── Gather data in parallel ───────────────────────────────────────────────
    finnhub = FinnhubClient()
    try:
        quote, expirations, rv_raw = await asyncio.gather(
            finnhub.get_quote(sym),
            loop.run_in_executor(None, YFinanceClient.get_option_expirations, sym),
            loop.run_in_executor(None, YFinanceClient.get_realized_vol_data, sym),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}")
    finally:
        await finnhub.close()

    current_price: float | None = float(quote.get("c") or 0) or None

    # Ticker + next earnings from DB
    ticker_row = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    earnings_str: str | None = None
    ticker_name: str = sym
    if ticker_row:
        ticker_name = ticker_row.name or sym
        ned = (await db.execute(
            select(func.min(Event.event_date))
            .where(Event.event_type == "earnings", Event.event_date >= today,
                   Event.ticker_id == ticker_row.id)
        )).scalar_one_or_none()
        if ned:
            earnings_str = ned.isoformat() if hasattr(ned, "isoformat") else str(ned)

    # Pick expiration (same logic as expected-move endpoint)
    chosen_exp: str | None = None
    if expirations:
        if earnings_str:
            post = [e for e in expirations if e >= earnings_str]
            chosen_exp = post[0] if post else expirations[-1]
        else:
            week_out = (today + timedelta(days=7)).isoformat()
            chosen_exp = next((e for e in expirations if e >= week_out), expirations[0])

    # Options chain
    chain: dict = {"calls": [], "puts": []}
    if chosen_exp:
        chain = await loop.run_in_executor(None, YFinanceClient.get_option_chain, sym, chosen_exp)

    calls = chain.get("calls", [])
    puts  = chain.get("puts", [])

    # ATM strike, straddle, expected move, ATM IV
    atm_strike: float | None = None
    expected_move_pct: float | None = None
    expected_move_dollars: float | None = None
    implied_range_low: float | None = None
    implied_range_high: float | None = None
    atm_iv: float | None = None

    if calls and puts and current_price:
        intersection = {c["strike"] for c in calls} & {p["strike"] for p in puts}
        if intersection:
            atm_strike = min(intersection, key=lambda s: abs(s - current_price))
            atm_call = next((c for c in calls if c["strike"] == atm_strike), None)
            atm_put  = next((p for p in puts  if p["strike"] == atm_strike), None)
            call_price = _mid_or_last(atm_call["bid"], atm_call["ask"], atm_call["lastPrice"]) if atm_call else None
            put_price  = _mid_or_last(atm_put["bid"],  atm_put["ask"],  atm_put["lastPrice"])  if atm_put  else None
            if call_price is not None and put_price is not None:
                straddle = call_price + put_price
                expected_move_pct    = straddle / current_price
                expected_move_dollars = straddle
                implied_range_low    = current_price - straddle
                implied_range_high   = current_price + straddle
            ivs = [c["impliedVolatility"] for c in [atm_call, atm_put]
                   if c and c.get("impliedVolatility") is not None]
            atm_iv = sum(ivs) / len(ivs) if ivs else None

    # RV rank/percentile
    current_rv: float | None = rv_raw.get("current_rv")
    rv_series: list[float]   = rv_raw.get("rv_series", [])
    rv_rank: float | None    = None
    rv_percentile: float | None = None
    rv_min: float | None     = None
    rv_max: float | None     = None
    rv_sample_days: int      = rv_raw.get("sample_days", 0)

    if rv_series and current_rv is not None:
        rv_min = min(rv_series)
        rv_max = max(rv_series)
        rv_rank = (current_rv - rv_min) / (rv_max - rv_min) * 100 if rv_max > rv_min else 50.0
        rv_rank = round(max(0.0, min(100.0, rv_rank)), 1)
        rv_percentile = round(sum(1 for v in rv_series if v < current_rv) / len(rv_series) * 100, 1)

    # IV-RV spread (in percentage points)
    iv_rv_spread_pp: float | None = (
        round((atm_iv - current_rv) * 100, 1)
        if atm_iv is not None and current_rv is not None else None
    )

    # Historical earnings avg absolute 1d move
    avg_earn_move_pct: float | None = None
    earn_sample: int = 0
    if ticker_row:
        reactions = (await db.execute(
            select(HistoricalReaction).where(
                HistoricalReaction.ticker_id == ticker_row.id,
                HistoricalReaction.event_type == "earnings",
                HistoricalReaction.pct_change_1d.isnot(None),
            )
        )).scalars().all()
        abs_moves = [abs(float(r.pct_change_1d)) for r in reactions]  # stored as full pct (e.g. 2.77 = 2.77%)
        if abs_moves:
            avg_earn_move_pct = round(mean(abs_moves), 1)
            earn_sample = len(abs_moves)

    # Earnings window
    expiration_spans_earnings = False
    days_exp_past_earnings: int | None = None
    days_to_exp: int | None = None
    if chosen_exp:
        exp_obj = date.fromisoformat(chosen_exp)
        days_to_exp = (exp_obj - today).days
        if earnings_str:
            earn_obj = date.fromisoformat(earnings_str)
            if exp_obj >= earn_obj:
                expiration_spans_earnings = True
                days_exp_past_earnings = (exp_obj - earn_obj).days

    # ── Build pre-formatted fact strings (the model sees ONLY these) ──────────
    def _fp(v: float | None, d: int = 2) -> str:
        return f"${v:.{d}f}" if v is not None else "(unavailable)"

    def _fpct(v: float | None, d: int = 1) -> str:
        """0-1 decimal → formatted percent string."""
        return f"{v * 100:.{d}f}%" if v is not None else "(unavailable)"

    facts: dict = {
        "symbol":                    sym,
        "company_name":              ticker_name,
        "current_price":             _fp(current_price),
        "expected_move_pct":         f"±{expected_move_pct * 100:.1f}%" if expected_move_pct is not None else "(unavailable)",
        "expected_move_dollars":     f"±{_fp(expected_move_dollars)}" if expected_move_dollars is not None else "(unavailable)",
        "implied_range":             f"{_fp(implied_range_low)} – {_fp(implied_range_high)}" if implied_range_low is not None and implied_range_high is not None else "(unavailable)",
        "expiration_date":           chosen_exp or "(unavailable)",
        "days_to_expiration":        str(days_to_exp) if days_to_exp is not None else "(unavailable)",
        "atm_strike":                _fp(atm_strike),
        "atm_iv":                    _fpct(atm_iv),
        "next_earnings_date":        earnings_str or "(unavailable)",
        "expiration_spans_earnings": str(expiration_spans_earnings),
        "days_exp_past_earnings":    str(days_exp_past_earnings) if days_exp_past_earnings is not None else "N/A",
        "realized_vol_20d":          _fpct(current_rv),
        "rv_rank":                   f"{rv_rank:.1f}" if rv_rank is not None else "(unavailable)",
        "rv_percentile":             f"{rv_percentile:.1f}" if rv_percentile is not None else "(unavailable)",
        "rv_1yr_range":              f"{_fpct(rv_min)} – {_fpct(rv_max)}" if rv_min is not None and rv_max is not None else "(unavailable)",
        "rv_sample_days":            str(rv_sample_days),
        "iv_rv_spread":              (f"{iv_rv_spread_pp:+.1f}pp" if iv_rv_spread_pp is not None else "(unavailable)"),
        "avg_earnings_1d_move":      f"±{avg_earn_move_pct:.1f}%" if avg_earn_move_pct is not None else "(unavailable)",
        "earnings_sample_size":      str(earn_sample) if earn_sample > 0 else "(unavailable)",
    }

    # Earnings window note — a full pre-written sentence so the model can't miscalculate
    if expiration_spans_earnings and days_exp_past_earnings is not None:
        earnings_window_note = (
            f"The {chosen_exp} expiration falls {days_exp_past_earnings} calendar days "
            f"after the {earnings_str} earnings date, so the implied move covers the full "
            f"period through expiration, not just the earnings reaction."
        )
    else:
        earnings_window_note = "(unavailable — expiration does not span the next earnings date)"

    # ── Prompt ────────────────────────────────────────────────────────────────
    prompt = f"""\
You are a senior options trader narrating what you see on the screen for {sym} ({ticker_name}).
Write exactly 2–4 tight sentences of interpretive prose for a sophisticated reader of a financial research tool.

INJECTED FACTS — use ONLY these exact strings verbatim for every number you state.
Do NOT derive, approximate, recompute, or restate any figure differently from what appears below.
If a fact says "(unavailable)", omit that thread entirely — do not guess or fabricate.

--- FACT BLOCK ---
Symbol / Company:           {sym} / {ticker_name}
Current price:              {facts["current_price"]}

EXPECTED MOVE (options-implied, ATM straddle):
  Implied move:             {facts["expected_move_pct"]} ({facts["expected_move_dollars"]}) by {facts["expiration_date"]} ({facts["days_to_expiration"]} calendar days)
  Implied price range:      {facts["implied_range"]}
  ATM strike / ATM IV:      {facts["atm_strike"]} / {facts["atm_iv"]}

EARNINGS CONTEXT:
  Next earnings date:       {facts["next_earnings_date"]}
  Expiration spans earnings:{facts["expiration_spans_earnings"]}
  Earnings window note:     {earnings_window_note}

VOLATILITY:
  20-day realized vol:      {facts["realized_vol_20d"]}
  RV rank (0–100):          {facts["rv_rank"]}   [0=lowest in past year, 100=highest]
  RV percentile:            {facts["rv_percentile"]}   [{facts["rv_percentile"]}% of the past {facts["rv_sample_days"]} trading days had lower realized vol]
  1-yr RV range:            {facts["rv_1yr_range"]}
  IV − RV spread:           {facts["iv_rv_spread"]}   [positive = options pricing more vol than recently delivered; negative = options cheap vs realized]

HISTORICAL EARNINGS (from actual past reactions):
  Avg absolute 1-day move:  {facts["avg_earnings_1d_move"]}
  Based on:                 {facts["earnings_sample_size"]} past earnings events
--- END FACT BLOCK ---

STRICT RULES:
1. Every number you write MUST be copied verbatim from the fact block. No rounding, reformatting, or paraphrasing of figures.
2. Write PROSE ONLY — no bullets, headers, lists, or markdown.
3. Cover these threads in a natural flow across 2–4 sentences:
   a. What the market is pricing: state the implied move, implied range, and expiration.
   b. The vol context: connect the RV rank and the IV−RV spread — is implied vol historically cheap or rich vs what the stock has recently delivered? Be specific about what this looks like from each side of the trade.
   c. If expiration spans earnings (True): use the earnings window note verbatim or paraphrase it — note the expiration extends past earnings.
   d. If available: briefly note the historical average earnings-day move for comparison.
4. You MAY describe the setup descriptively from a premium-seller or premium-buyer perspective — but NO trade recommendations, no "you should buy/sell," no price targets.
5. Omit any thread where the fact says "(unavailable)".
6. Do NOT add disclaimers or caveats — the UI handles that.
7. Target 60–100 words. Be specific and grounded; no generic filler.\
"""

    print(f"[options-read] Generating for {sym} | facts: {json.dumps(facts, indent=2)}", flush=True)

    # ── Generate ──────────────────────────────────────────────────────────────
    client = AnthropicClient()
    try:
        gen = await client.generate_options_read(prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Options read generation failed: {exc}")

    generated_at = dt_datetime.now(tz=timezone.utc).isoformat()
    print(
        f"[options-read] {sym}: {gen['input_tokens']} in / {gen['output_tokens']} out tokens",
        flush=True,
    )

    # ── Cache for the calendar day ────────────────────────────────────────────
    try:
        await _set_meta(db, cache_key, json.dumps({
            "content": gen["content"], "facts": facts,
            "model_used": gen["model_used"], "generated_at": generated_at,
        }))
        await db.commit()
    except Exception as exc:
        print(f"[options-read] Cache write failed for {sym}: {exc}", flush=True)

    return OptionsReadRead(
        symbol=sym, content=gen["content"], facts=facts,
        model_used=gen["model_used"], generated_at=generated_at,
        cached=False, as_of=as_of,
    )


@router.get("/rv/{symbol}", response_model=RealizedVolRead)
async def get_realized_vol(symbol: str) -> RealizedVolRead:
    """20-day annualized realized (historical) volatility + trailing 1-year rank and percentile.

    Rank = where today's RV sits in its 1-year [min, max] range (0-100).
    Percentile = % of the trailing 252 trading days where RV was below today's (0-100).
    """
    sym = symbol.upper()
    loop = asyncio.get_event_loop()
    as_of = dt_datetime.now(tz=timezone.utc).isoformat()

    data: dict = await loop.run_in_executor(None, YFinanceClient.get_realized_vol_data, sym)

    current_rv: float | None = data.get("current_rv")
    rv_series: list[float] = data.get("rv_series", [])
    sample_days: int = data.get("sample_days", 0)

    if not rv_series or current_rv is None:
        return RealizedVolRead(
            symbol=sym, current_rv=None,
            rv_rank=None, rv_percentile=None,
            rv_min_1y=None, rv_max_1y=None,
            sample_days=0, window_days=20, as_of=as_of,
        )

    rv_min = min(rv_series)
    rv_max = max(rv_series)
    rv_rank = (current_rv - rv_min) / (rv_max - rv_min) * 100 if rv_max > rv_min else 50.0
    rv_rank = max(0.0, min(100.0, rv_rank))
    rv_percentile = sum(1 for v in rv_series if v < current_rv) / len(rv_series) * 100

    return RealizedVolRead(
        symbol=sym,
        current_rv=current_rv,
        rv_rank=round(rv_rank, 1),
        rv_percentile=round(rv_percentile, 1),
        rv_min_1y=rv_min,
        rv_max_1y=rv_max,
        sample_days=sample_days,
        window_days=20,
        as_of=as_of,
    )


@router.get("/{ticker_id}", response_model=TickerRead)
async def get_ticker(ticker_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Ticker:
    ticker = await db.get(Ticker, ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@router.patch("/{ticker_id}", response_model=TickerRead)
async def update_ticker(
    ticker_id: uuid.UUID,
    payload: TickerUpdate,
    db: AsyncSession = Depends(get_db),
) -> Ticker:
    ticker = await db.get(Ticker, ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticker, field, value)
    await db.commit()
    await db.refresh(ticker)
    return ticker


@router.delete("/{ticker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticker(ticker_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    ticker = await db.get(Ticker, ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    await db.delete(ticker)
    await db.commit()
