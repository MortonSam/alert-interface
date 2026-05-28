import asyncio
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.ticker import Ticker
from app.models.historical_reaction import HistoricalReaction
from app.schemas.ticker import EarningsMarker, SparklinePoint, TickerChartRead, TickerCreate, TickerQuoteRead, TickerRead, TickerUpdate
from app.services.finnhub_client import FinnhubClient
from app.services.yfinance_client import YFinanceClient

router = APIRouter(prefix="/tickers", tags=["tickers"])


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
