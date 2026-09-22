"""One exclusion list for every consumer of price history, applied at read time.

A ticker whose latest rv_snapshot is ``data_error`` had a >50% daily move with
no volume spike and no recorded corporate action (rv_math): its price history
is not trusted. Every reader of historical_reactions and analyst stats skips
that ticker's rows and states EXCLUSION_REASON; the rows themselves stay in
the tables, so a verdict that later reverses (a split event arrives, the
guard is refined) costs nothing. Nothing here deletes.

The list is read from the stored snapshot, not recomputed, so every consumer
sees the same decision the RV job made; the RV step runs before every
reaction step in the nightly order, so they act on tonight's verdict.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rv_snapshot import RVSnapshot

EXCLUDED_STATUS = "data_error"
EXCLUSION_REASON = (
    "Price history for this ticker failed the RV guard (a move of more than 50% in one day "
    "with no volume spike and no recorded split or dividend), so reactions computed from it are not shown"
)

_latest = (
    select(RVSnapshot.symbol, RVSnapshot.status)
    .distinct(RVSnapshot.symbol)
    .order_by(RVSnapshot.symbol, RVSnapshot.as_of_date.desc())
    .subquery("latest_rv")
)
EXCLUDED_SYMBOLS = select(_latest.c.symbol).where(_latest.c.status == EXCLUDED_STATUS)


def not_excluded(symbol_column):
    """WHERE clause: the symbol is not on the exclusion list (for ORM readers)."""
    return symbol_column.notin_(EXCLUDED_SYMBOLS)


# Raw-SQL readers append this
EXCLUDED_SYMBOLS_SQL = """(SELECT symbol FROM (SELECT DISTINCT ON (symbol) symbol, status FROM rv_snapshots
                            ORDER BY symbol, as_of_date DESC) latest_rv WHERE status = 'data_error')"""


async def excluded_symbols(session: AsyncSession) -> set[str]:
    return set((await session.execute(EXCLUDED_SYMBOLS)).scalars().all())


async def is_excluded(session: AsyncSession, symbol: str) -> bool:
    return symbol in await excluded_symbols(session)


async def exclusion_reason(session: AsyncSession, symbol: str) -> str | None:
    return EXCLUSION_REASON if await is_excluded(session, symbol) else None


async def exclusion_list(session: AsyncSession, label: str) -> set[str]:
    """The list, printed for a step's log. Pipelines drop these symbols from their candidates and write nothing for them."""
    excluded = await excluded_symbols(session)
    if excluded:
        print(f"{label}: skipping {len(excluded)} ticker(s) whose price history is excluded "
              f"(RV data_error): {', '.join(sorted(excluded))}; their stored rows stay and are hidden at read time.",
              flush=True)
    return excluded
