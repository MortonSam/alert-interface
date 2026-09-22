"""Split basis of stored per-share values.

Yahoo restates both its estimate and its reported EPS after a stock split, on
the current share count. A row frozen before a split keeps its estimate on the
old basis while a refresh brings the actual on the new one, and the two no
longer compare. These helpers read the recorded split events after a quarter
and tell whether a restated actual is a re-basing, so the frozen estimate can
be re-based by the same factor.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

REBASE_TOLERANCE = 0.03   # |stored/incoming - R| / R for a restated actual to count as a split re-basing
BASIS_CHECK_TOLERANCE = 0.15   # validate: estimate/actual within this of a split factor is on the wrong basis
MIN_SPLIT_FACTOR = 1.25   # smaller factors (spin-off ratios like 37:35, 16:15) are indistinguishable from a surprise


def ratio_factor(split_ratio: str) -> float:
    """"2:1" -> 2.0, "3:2" -> 1.5, "1:50" -> 0.02 (reverse split)."""
    a, b = split_ratio.split(":")
    return float(a) / float(b)


def suffix_factors(factors: list[float]) -> list[float]:
    """Cumulative factors of the most recent k splits, k = 1..n, oldest-first input.

    A row frozen between two splits misses only the later ones, so the
    candidate re-basing factors are the suffix products. Reverse splits are
    expressed as their inverse so every candidate is >= 1; candidates under
    MIN_SPLIT_FACTOR are dropped.
    """
    out: list[float] = []
    acc = 1.0
    for f in reversed(factors):
        acc *= f
        cand = acc if acc >= 1 else 1 / acc
        if cand >= MIN_SPLIT_FACTOR:
            out.append(cand)
    return out


def rebase_factor(stored_actual: Decimal | None, incoming_actual: Decimal | None, factors: list[float]) -> float | None:
    """The split factor a restated actual was divided by, or None if it was not a re-basing."""
    if stored_actual is None or incoming_actual is None or incoming_actual == 0 or stored_actual == incoming_actual:
        return None
    observed = abs(float(stored_actual) / float(incoming_actual))
    for r in suffix_factors(factors):
        if abs(observed - r) / r <= REBASE_TOLERANCE:
            return r
    return None


def wrong_basis_factor(estimate: Decimal | None, actual: Decimal | None, factors: list[float]) -> float | None:
    """The split factor the estimate appears to be stale by, or None.

    Only the estimate can be stale: actuals are rewritten on every refresh on
    Yahoo's current basis, while a frozen estimate keeps the basis it had.
    """
    if estimate is None or actual is None or estimate == 0 or actual == 0:
        return None
    ea = abs(float(estimate) / float(actual))
    for r in suffix_factors(factors):
        if abs(ea - r) / r <= BASIS_CHECK_TOLERANCE:
            return r
    return None


_SPLITS_CACHE: dict[uuid.UUID, list[tuple[date, float]]] = {}


async def load_splits(session: AsyncSession, ticker_id: uuid.UUID) -> list[tuple[date, float]]:
    """Recorded splits for a ticker as (date, factor), oldest first; cached per process."""
    if ticker_id not in _SPLITS_CACHE:
        rows = (await session.execute(text("""
            SELECT event_date, metadata->>'split_ratio' AS ratio FROM events
            WHERE ticker_id = :t AND event_type = 'split' AND metadata->>'split_ratio' IS NOT NULL
            ORDER BY event_date
        """), {"t": ticker_id})).all()
        _SPLITS_CACHE[ticker_id] = [(d, ratio_factor(r)) for d, r in rows]
    return _SPLITS_CACHE[ticker_id]


def factors_after(splits: list[tuple[date, float]], event_date: date) -> list[float]:
    return [f for d, f in splits if d > event_date]
