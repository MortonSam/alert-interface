"""Which Intrinio security record a ticker is, on which dates.

Intrinio reuses tickers across companies (PARA is Banzai International today) and gives a re-domiciled
company a new record with a new FIGI, so every read goes by record id, never by ticker, and every date
resolves to exactly one record. The build script fetches each active ticker's current record; the
predecessors below are data, found by the security-history endpoint on 2026-10-01; PSKY keeps its stored
rows before 2025-08-07 under a stored_history row because its predecessor, Paramount Global class B, is a
different security.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CURRENT, PREDECESSOR, STORED_HISTORY = "current", "predecessor", "stored_history"
INTRINIO, STORED = "intrinio", "stored"
STORED_START = date(2021, 7, 1)              # the oldest date any stored reaction window reaches back to
STALE_SESSIONS = 2                           # a current record whose last price is older than this is being replaced


@dataclass(frozen=True)
class Record:
    symbol: str
    intrinio_security_id: str | None
    figi: str | None
    composite_figi: str | None
    name: str | None
    valid_from: date
    valid_to: date | None
    role: str
    source: str


# symbol -> (predecessor record, its FIGI, its name, its first price date, its last price date, the current record's first day)
PREDECESSORS: dict[str, dict] = {
    "OKE":  {"id": "sec_ybYl7z", "figi": "BBG000BQHJ81", "composite_figi": "BBG000BQHGR6", "name": "Oneok Inc.",
             "valid_from": date(1985, 7, 1), "valid_to": date(2026, 9, 14), "current_from": date(2026, 9, 15)},
    "TEL":  {"id": "sec_gAD5Jy", "figi": "BBG000RGM768", "composite_figi": "BBG000RGM5P1", "name": "TE Connectivity Ltd",
             "valid_from": date(2007, 6, 14), "valid_to": date(2024, 9, 27), "current_from": date(2024, 9, 30)},
    "FERG": {"id": "sec_g4aDDb", "figi": "BBG00P5M4V43", "composite_figi": "BBG00P5M4V07", "name": "Ferguson Plc.",
             "valid_from": date(2019, 5, 17), "valid_to": date(2024, 7, 31), "current_from": date(2024, 8, 1)},
    "CRH":  {"id": "sec_5ydnRX", "figi": "BBG000BBLSM3", "composite_figi": "BBG000BBLR09", "name": "CRH Plc",
             "valid_from": date(1993, 2, 19), "valid_to": date(2023, 9, 22), "current_from": date(2023, 9, 25)},
}

# symbol -> the span the stored rows keep their yfinance history for, and the day the current record takes over
STORED_HISTORY_ROWS: dict[str, dict] = {
    "PSKY": {"valid_from": STORED_START, "valid_to": date(2025, 8, 6), "current_from": date(2025, 8, 7),
             "name": "Paramount Global class B (Intrinio sec_gVN622, a different security): stored yfinance history"},
}


def plan_records(symbol: str, current: dict) -> list[Record]:
    """The rows a symbol should hold, from its current Intrinio record (the /securities/{ticker} body)."""
    pred = PREDECESSORS.get(symbol)
    stored = STORED_HISTORY_ROWS.get(symbol)
    first = current.get("first_stock_price")
    first = date.fromisoformat(first) if isinstance(first, str) else (first or STORED_START)
    if pred:
        current_from = pred["current_from"]
    elif stored:
        current_from = stored["current_from"]
    else:
        current_from = first
    rows = [Record(symbol, current.get("id"), current.get("figi"), current.get("composite_figi"), current.get("name"),
                   current_from, None, CURRENT, INTRINIO)]
    if pred:
        rows.append(Record(symbol, pred["id"], pred["figi"], pred["composite_figi"], pred["name"], pred["valid_from"], pred["valid_to"], PREDECESSOR, INTRINIO))
    if stored:
        rows.append(Record(symbol, None, None, None, stored["name"], stored["valid_from"], stored["valid_to"], STORED_HISTORY, STORED))
    return sorted(rows, key=lambda r: r.valid_from)


def resolve(records: list[Record], on: date) -> Record | None:
    """The one record covering `on`, or None."""
    hits = [r for r in records if r.valid_from <= on and (r.valid_to is None or on <= r.valid_to)]
    return hits[0] if len(hits) == 1 else None


def _has_session(a: date, b: date) -> bool:
    """Whether any NYSE session falls in [a, b]."""
    from app.services.trading_calendar import is_trading_day
    d = a
    while d <= b:
        if is_trading_day(d):
            return True
        d += timedelta(days=1)
    return False


def coverage_problems(records: list[Record], start: date, end: date) -> list[str]:
    """Every way the records fail to tile [start, end] with exactly one record per date.

    A gap that holds no NYSE session (a weekend between a predecessor's last day and its successor's first) is
    not a problem: no bar can fall in it."""
    out: list[str] = []
    if not records:
        return [f"no record at all for {start.isoformat()}..{end.isoformat()}"]
    if not any(r.role == CURRENT for r in records):
        out.append("no current record")
    rows = sorted(records, key=lambda r: r.valid_from)
    # overlaps between consecutive ranges, and open-ended rows that are not last
    for a, b in zip(rows, rows[1:]):
        if a.valid_to is None or a.valid_to >= b.valid_from:
            out.append(f"{a.role} {a.valid_from.isoformat()}..{a.valid_to.isoformat() if a.valid_to else 'open'} overlaps {b.role} from {b.valid_from.isoformat()}")
    # gaps: walk the dates the ranges cover
    cursor = start
    for r in rows:
        if r.valid_to is not None and r.valid_to < cursor:
            continue
        if r.valid_from > cursor and _has_session(cursor, r.valid_from - timedelta(days=1)):
            out.append(f"gap {cursor.isoformat()}..{(r.valid_from - timedelta(days=1)).isoformat()}")
        if r.valid_to is None:
            cursor = end + timedelta(days=1)
            break
        cursor = max(cursor, r.valid_to + timedelta(days=1))
    if cursor <= end and _has_session(cursor, end):
        out.append(f"gap {cursor.isoformat()}..{end.isoformat()}")
    return out
