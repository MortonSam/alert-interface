import asyncio
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
from app.schemas.options import ExpectedMoveRead, HistoricalMoveStats, OptionsChainRead, OptionContractRead
from app.schemas.ticker import EarningsMarker, SparklinePoint, TickerChartRead, TickerCreate, TickerQuoteRead, TickerRead, TickerUpdate
from app.services.finnhub_client import FinnhubClient
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


@router.get("/chart/{symbol}", response_model=TickerChartRead)
async def get_ticker_chart(
    symbol: str,
    period: str = "1y",
    db: AsyncSession = Depends(get_db),
) -> TickerChartRead:
    """Daily price history + earnings markers for the interactive chart."""
    sym = symbol.upper()

    # yfinance history runs sync — offload to thread pool
    loop = asyncio.get_event_loop()
    history_raw: list[dict] = await loop.run_in_executor(
        None, YFinanceClient.get_daily_closes, sym, period
    )

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

    return TickerChartRead(symbol=sym, period=period, history=history, earnings_markers=markers)


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

    chain = await loop.run_in_executor(None, YFinanceClient.get_option_chain, sym, chosen_exp)

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
    chain = await loop.run_in_executor(None, YFinanceClient.get_option_chain, sym, chosen)

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
