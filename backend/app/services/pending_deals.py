"""Tickers under a definitive cash acquisition: their price tracks the deal, not the business, so earnings and options
figures are paused for them, with one note naming the deal price.

A row exists only when written by scripts/set_pending_deal after its filing check passed, so the hold has no feature flag:
it acts on rows Sam approved and nothing else. A held ticker
  - holds the implied_move and typical_move facts (services/fact_holds), so the strip, the Overview, Discover's lines,
    Ask Ivy and the briefing drop them as they drop any held fact;
  - shows DEAL_NOTE in place of the expected move, the earnings-move statistics, the options chain, implied volatility,
    put/call and Ivy's Read;
  - gets no pick (compute_alert_pick refuses it, auto_pick skips it) and no Build draft;
  - leaves Discover's suggestions, unusually active and just reported lists.
validate's pending_deal_price_band warns when a held stock's close is more than PRICE_BAND_PCT from the deal price.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

HELD_FACTS = ("implied_move", "typical_move")
HOLD_CHECK = "pending_deal"
PRICE_BAND_PCT = 5.0
DEAL_NOTE = ("This company has agreed to be acquired for {price} a share in cash, so its price now tracks the deal rather than its "
             "business. Earnings and options figures are paused.")


@dataclass(frozen=True)
class Deal:
    symbol: str
    price: float
    acquirer: str
    agreed_on: date
    expected_close: str | None
    filing_url: str


def fmt_price(price: float) -> str:
    return f"${price:,.2f}"


def note_for(deal: Deal) -> str:
    """The visitor note, its price from the stored row."""
    return DEAL_NOTE.format(price=fmt_price(deal.price))


_SQL = "SELECT symbol, price_per_share, acquirer, agreed_on, expected_close, filing_url FROM pending_deals WHERE status = 'active'"


def _deal(r) -> Deal:
    return Deal(r[0], float(r[1]), r[2], r[3], r[4], r[5])


async def deals_for(db, symbols: list[str] | None = None) -> dict[str, Deal]:
    """{symbol: Deal} for the active holds among `symbols` (all of them when None)."""
    if symbols is not None and not symbols:
        return {}
    sql, params = (_SQL, {}) if symbols is None else (_SQL + " AND symbol = ANY(:s)", {"s": list(symbols)})
    return {r[0]: _deal(r) for r in (await db.execute(text(sql), params)).all()}


async def deal_for(db, symbol: str) -> Deal | None:
    return (await deals_for(db, [symbol.upper()])).get(symbol.upper())


async def held_symbols(db) -> set[str]:
    return set(await deals_for(db))


def deal_for_sync(conn, symbol: str) -> Deal | None:
    r = conn.execute(text(_SQL + " AND symbol = :s"), {"s": symbol.upper()}).first()
    return _deal(r) if r else None


def not_held(column):
    """A SQL condition: `column` (a ticker symbol) is not under an active pending deal."""
    from sqlalchemy import select
    return ~column.in_(select(text("symbol")).select_from(text("pending_deals")).where(text("status = 'active'")))
