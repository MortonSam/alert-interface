"""One exclusion list for every consumer of price history.

A ticker whose latest rv_snapshot is ``data_error`` had a >50% daily move with
no volume spike and no recorded corporate action (rv_math): its price history
is not trusted. Nothing computed from that history may be stored or shown, so
the reaction pipelines (earnings, FOMC, analyst actions) skip the ticker and
clear what they hold for it, and validate_data checks nothing remains.

The list is read from the stored snapshot, not recomputed, so every consumer
sees the same decision the RV job made. The reaction steps run before the RV
step in the nightly order, so they act on the previous night's decision.
"""
from __future__ import annotations

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analyst_reaction_stats import AnalystReactionStats
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker

EXCLUDED_STATUS = "data_error"

_LATEST_STATUS_SQL = text("""
    SELECT DISTINCT ON (symbol) symbol, status
    FROM rv_snapshots
    ORDER BY symbol, as_of_date DESC
""")


async def excluded_symbols(session: AsyncSession) -> set[str]:
    """Symbols whose latest rv_snapshot has status data_error."""
    rows = (await session.execute(_LATEST_STATUS_SQL)).all()
    return {symbol for symbol, status in rows if status == EXCLUDED_STATUS}


async def clear_excluded(session: AsyncSession, symbols: set[str]) -> dict[str, int]:
    """Delete every stored reaction row and analyst stats row for the symbols.

    Returns {"reactions": n, "stats": n}. Commits nothing; the caller does.
    """
    if not symbols:
        return {"reactions": 0, "stats": 0}
    ticker_ids = select(Ticker.id).where(Ticker.symbol.in_(symbols))
    reactions = await session.execute(
        delete(HistoricalReaction).where(HistoricalReaction.ticker_id.in_(ticker_ids))
    )
    stats = await session.execute(
        delete(AnalystReactionStats).where(AnalystReactionStats.symbol.in_(symbols))
    )
    return {"reactions": reactions.rowcount, "stats": stats.rowcount}


async def apply_exclusion(session: AsyncSession, label: str) -> set[str]:
    """Read the list, clear what the excluded tickers hold, commit, and print.

    Every reaction pipeline calls this before choosing its candidates and then
    drops the returned symbols from them.
    """
    excluded = await excluded_symbols(session)
    if excluded:
        counts = await clear_excluded(session, excluded)
        await session.commit()
        print(
            f"{label}: skipping {len(excluded)} ticker(s) whose price history is excluded "
            f"(RV data_error): {', '.join(sorted(excluded))}; "
            f"cleared {counts['reactions']} reaction row(s), {counts['stats']} stats row(s).",
            flush=True,
        )
    return excluded
