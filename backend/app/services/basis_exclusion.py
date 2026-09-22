"""Rows whose EPS actual and estimate were reported on different bases.

eps_basis_checks.basis_mismatch is the stored, dated verdict (check_eps_basis).
Such a row carries no Beat/Miss: its stored outcome is 'unknown', every beat
statistic leaves it out and states how many were left out, and the ticker
page shows the reason below. One reason string, delivered by the API.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BASIS_UNCLEAR_REASON = "EPS basis unclear (actual and estimate reported on different bases)"


def excluded_note(count: int) -> str | None:
    """Sentence stating the exclusion wherever a rate is shown; None when nothing was excluded."""
    if count <= 0:
        return None
    q = "quarter" if count == 1 else "quarters"
    return f"{count} {q} excluded: {BASIS_UNCLEAR_REASON}"


async def basis_mismatch_dates(session: AsyncSession, ticker_id: uuid.UUID) -> set[date]:
    rows = (await session.execute(text(
        "SELECT event_date FROM eps_basis_checks WHERE ticker_id = :t AND basis_mismatch"
    ), {"t": ticker_id})).scalars().all()
    return set(rows)


async def basis_mismatch_pairs(session: AsyncSession) -> set[tuple[uuid.UUID, date]]:
    rows = (await session.execute(text(
        "SELECT ticker_id, event_date FROM eps_basis_checks WHERE basis_mismatch"
    ))).all()
    return {(t, d) for t, d in rows}


async def apply_basis_exclusion(session: AsyncSession) -> tuple[int, int]:
    """Set outcome = 'unknown' on flagged rows; re-derive rows that stopped being flagged.

    Returns (cleared, restored). The caller commits.
    """
    cleared = (await session.execute(text("""
        UPDATE historical_reactions hr SET outcome = 'unknown'
        FROM eps_basis_checks c
        WHERE c.ticker_id = hr.ticker_id AND c.event_date = hr.event_date AND c.basis_mismatch
          AND hr.event_type = 'earnings' AND hr.outcome <> 'unknown'
    """))).rowcount
    restored = (await session.execute(text("""
        UPDATE historical_reactions hr
        SET outcome = CAST(CASE WHEN hr.eps_actual > hr.eps_estimate THEN 'beat'
                                WHEN hr.eps_actual < hr.eps_estimate THEN 'miss'
                                ELSE 'meet' END AS earnings_outcome_enum)
        WHERE hr.event_type = 'earnings' AND hr.outcome = 'unknown'
          AND hr.eps_actual IS NOT NULL AND hr.eps_estimate IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM eps_basis_checks c
                          WHERE c.ticker_id = hr.ticker_id AND c.event_date = hr.event_date AND c.basis_mismatch)
    """))).rowcount
    return cleared, restored
