"""Split basis of stored per-share values.

Yahoo restates both its estimate and its reported EPS after a stock split, on
the current share count. A row frozen before a split keeps its estimate on the
old basis while a refresh brings the actual on the new one, and the two no
longer compare. These helpers read the recorded split events after a quarter
and tell whether a restated actual is a re-basing, so the frozen estimate can
be re-based by the same factor.

Anchors. A row whose values differ by a split factor within a tight band is
an anchor for (factor, split). Once a ticker has an anchor, every other row
before that split whose frozen estimate is nearer to factor x actual than to
actual is on the stale basis too, however large its real surprise was (APH
2025-04-23: estimate 0.52 vs actual 0.32 is a 21% miss on the old basis and
a 23% beat on the new one; the tight band alone would keep the old one).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

REBASE_TOLERANCE = 0.03   # |stored/incoming - F| / F for a restated actual to count as a split re-basing
BASIS_CHECK_TOLERANCE = 0.15   # estimate/actual within this of a split factor makes the row an anchor
MIN_SPLIT_FACTOR = 1.25   # smaller factors (spin-off ratios like 37:35, 16:15) are indistinguishable from a surprise

Split = tuple[date, float]          # (split date, factor)
Candidate = tuple[float, date]      # (cumulative factor, earliest split date in the suffix)
Anchor = Candidate


def ratio_factor(split_ratio: str) -> float:
    """"2:1" -> 2.0, "3:2" -> 1.5, "1:50" -> 0.02 (reverse split)."""
    a, b = split_ratio.split(":")
    return float(a) / float(b)


def splits_after(splits: list[Split], event_date: date) -> list[Split]:
    return [(d, f) for d, f in splits if d > event_date]


def candidates(after: list[Split]) -> list[Candidate]:
    """Cumulative factors of the most recent k splits, k = 1..n, each with the date
    of the earliest split in that suffix.

    A row frozen between two splits misses only the later ones, so the
    candidate re-basing factors are the suffix products. Reverse splits are
    expressed as their inverse so every candidate is >= 1; candidates under
    MIN_SPLIT_FACTOR are dropped.
    """
    out: list[Candidate] = []
    acc = 1.0
    for d, f in reversed(after):
        acc *= f
        cand = acc if acc >= 1 else 1 / acc
        if cand >= MIN_SPLIT_FACTOR:
            out.append((cand, d))
    return out


def rebase_factor(stored_actual: Decimal | None, incoming_actual: Decimal | None, cands: list[Candidate]) -> Candidate | None:
    """The split a restated actual was re-based by, or None if it was not a re-basing."""
    if stored_actual is None or incoming_actual is None or incoming_actual == 0 or stored_actual == incoming_actual:
        return None
    observed = abs(float(stored_actual) / float(incoming_actual))
    for F, d in cands:
        if abs(observed - F) / F <= REBASE_TOLERANCE:
            return F, d
    return None


def wrong_basis_factor(estimate: Decimal | None, actual: Decimal | None, cands: list[Candidate]) -> Candidate | None:
    """The split the estimate appears to be stale by (tight band), or None.

    Only the estimate can be stale: actuals are rewritten on every refresh on
    Yahoo's current basis, while a frozen estimate keeps the basis it had.
    """
    if estimate is None or actual is None or estimate == 0 or actual == 0:
        return None
    ea = abs(float(estimate) / float(actual))
    for F, d in cands:
        if abs(ea - F) / F <= BASIS_CHECK_TOLERANCE:
            return F, d
    return None


def nearer_to_rebased(estimate: Decimal, actual: Decimal, factor: float) -> bool:
    """True when the estimate sits closer to factor x actual than to actual."""
    e, a = float(estimate), float(actual)
    return abs(e - factor * a) < abs(e - a)


def anchored_factor(estimate: Decimal | None, actual: Decimal | None, event_date: date,
                    anchors: set[Anchor]) -> Candidate | None:
    """The anchor whose split follows this row and whose factor the estimate is nearer to, or None."""
    if estimate is None or actual is None or actual == 0:
        return None
    for F, split_date in sorted(anchors):
        if event_date < split_date and nearer_to_rebased(estimate, actual, F):
            return F, split_date
    return None


def stale_factor(estimate: Decimal | None, actual: Decimal | None, event_date: date,
                 cands: list[Candidate], anchors: set[Anchor]) -> Candidate | None:
    """Tight band first, then the ticker's anchors."""
    return wrong_basis_factor(estimate, actual, cands) or anchored_factor(estimate, actual, event_date, anchors)


def find_anchors(rows: list[tuple[date, Decimal | None, Decimal | None, Decimal | None]],
                 splits: list[Split]) -> set[Anchor]:
    """Anchors from a ticker's rows: (event_date, stored_estimate, stored_actual, incoming_actual | None).

    A row anchors when its incoming actual is a re-basing of the stored one,
    or its stored estimate and actual differ by a split factor within the band.
    """
    anchors: set[Anchor] = set()
    for event_date, estimate, actual, incoming in rows:
        cands = candidates(splits_after(splits, event_date))
        hit = rebase_factor(actual, incoming, cands) or wrong_basis_factor(estimate, actual, cands)
        if hit:
            anchors.add(hit)
    return anchors


_SPLITS_CACHE: dict[uuid.UUID, list[Split]] = {}


async def load_splits(session: AsyncSession, ticker_id: uuid.UUID) -> list[Split]:
    """Recorded splits for a ticker as (date, factor), oldest first; cached per process."""
    if ticker_id not in _SPLITS_CACHE:
        rows = (await session.execute(text("""
            SELECT event_date, metadata->>'split_ratio' AS ratio FROM events
            WHERE ticker_id = :t AND event_type = 'split' AND metadata->>'split_ratio' IS NOT NULL
            ORDER BY event_date
        """), {"t": ticker_id})).all()
        _SPLITS_CACHE[ticker_id] = [(d, ratio_factor(r)) for d, r in rows]
    return _SPLITS_CACHE[ticker_id]


async def load_anchors(session: AsyncSession, ticker_id: uuid.UUID,
                       incoming_actuals: dict[date, Decimal | None]) -> set[Anchor]:
    """Anchors for a ticker from its stored earnings rows and the actuals about to be written."""
    splits = await load_splits(session, ticker_id)
    if not splits:
        return set()
    rows = (await session.execute(text("""
        SELECT event_date, eps_estimate, eps_actual FROM historical_reactions
        WHERE ticker_id = :t AND event_type = 'earnings' AND eps_actual IS NOT NULL
    """), {"t": ticker_id})).all()
    return find_anchors([(d, e, a, incoming_actuals.get(d)) for d, e, a in rows], splits)
