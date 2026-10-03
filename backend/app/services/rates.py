"""The solver's rate: FRED DTB3, fetched daily, stored with its own date, read fail-closed.

FRED publishes the series as a CSV without a key (fredgraph.csv). The step stores every row it gets; a reader
asks for the value on the chain date and gets the latest published value at or before it, provided that value is
no older than RATE_MAX_AGE_SESSIONS sessions. Otherwise there is no rate and the step says so and stops.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.rate import Rate
from app.services.iv_solver import RATE_MAX_AGE_SESSIONS, RATE_SCALE, RATE_SERIES

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@dataclass(frozen=True)
class RateOn:
    rate: float | None       # annual decimal, or None
    rate_date: date | None
    reason: str | None       # why rate is None


def parse_fred_csv(body: str) -> list[tuple[date, float]]:
    """(date, percent) rows; FRED writes '.' for a day with no observation."""
    out = []
    for row in csv.DictReader(io.StringIO(body)):
        d, v = row.get("observation_date") or row.get("DATE"), row.get(RATE_SERIES) or next((row[k] for k in row if k not in ("observation_date", "DATE")), None)
        if not d or v in (None, "", "."):
            continue
        try:
            out.append((date.fromisoformat(d), float(v)))
        except ValueError:
            continue
    return out


async def fetch_series(series: str = RATE_SERIES, since: date | None = None) -> list[tuple[date, float]]:
    params = {"id": series}
    if since:
        params["cosd"] = since.isoformat()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(FRED_CSV_URL, params=params)
        r.raise_for_status()
    return parse_fred_csv(r.text)


async def store_rates(session, rows: list[tuple[date, float]], series: str = RATE_SERIES) -> int:
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    stmt = insert(Rate).values([{"series": series, "date": d, "value": v, "fetched_at": now} for d, v in rows])
    await session.execute(stmt.on_conflict_do_update(constraint="pk_rates", set_={"value": stmt.excluded.value, "fetched_at": stmt.excluded.fetched_at}))
    return len(rows)


def pick_rate(rows: list[tuple[date, float]], on: date, max_sessions: int = RATE_MAX_AGE_SESSIONS) -> RateOn:
    """Pure: the latest published value at or before `on`, if within max_sessions sessions of it."""
    from app.services.trading_calendar import sessions_after
    before = sorted((d, v) for d, v in rows if d <= on)
    if not before:
        return RateOn(None, None, f"no {RATE_SERIES} value stored on or before {on.isoformat()}")
    d, v = before[-1]
    age = sessions_after(d, on)
    if age > max_sessions:
        return RateOn(None, None, f"latest {RATE_SERIES} value is dated {d.isoformat()}, {age} sessions before {on.isoformat()} (limit {max_sessions})")
    return RateOn(v * RATE_SCALE, d, None)


async def rate_on(session, on: date, series: str = RATE_SERIES) -> RateOn:
    rows = (await session.execute(select(Rate.date, Rate.value).where(Rate.series == series, Rate.date <= on).order_by(Rate.date.desc()).limit(20))).all()
    return pick_rate([(r.date, float(r.value)) for r in rows], on)
