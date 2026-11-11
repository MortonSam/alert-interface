"""The market values on file (market_values, written by scripts/compute_market_values): what a page reads. A row with no value
(a company on the hold-out list, or one that could not be worked out) is never returned as a figure, and the vendor's market cap
is never read here."""
from __future__ import annotations

from sqlalchemy import text

from app.services.market_value import MARKET_VALUE_VERSION

FILINGS = "filings"      # TickerRead.market_cap_basis: shares from the latest 10-Q or 10-K cover, each class at its own close

# the tickers a walkthrough run reads: the company's own market value beside each (market_value, None when held or not worked out;
# market_value_as_of, the close it rests on; company, the key its share classes share). tickers.market_cap, the vendor's, comes
# along only to order stocks by size (a rival, the featured pick) and is never displayed.
TICKERS_WITH_VALUE = """SELECT t.id, t.symbol, t.name, t.sector, t.industry, t.index_member, t.market_cap, mv.value::float8 AS market_value,
        mv.close_date AS market_value_as_of, COALESCE(mv.company, t.symbol) AS company
    FROM tickers t LEFT JOIN market_values mv ON mv.symbol = t.symbol AND mv.version = """ + str(MARKET_VALUE_VERSION) + """
    WHERE t.is_active ORDER BY t.symbol"""


async def values(db, symbols: list[str] | None = None) -> dict[str, dict]:
    """{symbol: {value, close_date, shares, shares_as_of, form, filed, company}} for every stock with a figure on file under the
    current version (all of them, or the symbols asked for)."""
    rows = (await db.execute(text("""SELECT symbol, company, value::float8 AS value, shares::float8 AS shares, shares_as_of, close_date, form, filed
        FROM market_values WHERE value IS NOT NULL AND version = :v AND (CAST(:s AS text[]) IS NULL OR symbol = ANY(CAST(:s AS text[])))"""),
        {"v": MARKET_VALUE_VERSION, "s": symbols})).mappings().all()
    return {r["symbol"]: dict(r) for r in rows}


def show(read, figures: dict[str, dict]):
    """A TickerRead with the company's own market value in place of the vendor's (MARKET_VALUE_ENABLED): the figure on file and the
    close it rests on, or nothing at all for a stock with no figure. The vendor's market cap never passes through here."""
    f = figures.get(read.symbol)
    read.market_cap = round(f["value"]) if f else None
    read.market_cap_as_of = f["close_date"] if f else None
    read.market_cap_basis = FILINGS
    return read

