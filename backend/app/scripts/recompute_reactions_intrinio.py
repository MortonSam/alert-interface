"""One-time: recompute every historical_reactions row from the stored Intrinio shadow bars and set price_source.

Dry run by default: for every row (earnings, FOMC, analyst) it recomputes the move with the seeders' own functions
from price_bars_shadow (adjusted from the stored factors, SPY as the session calendar) and reports per event type
how many rows reproduce within TOLERANCE_PP on the one-day move, how many change and by how much (ten largest),
how many fill a stored null, how many lose a value Intrinio has no bar for, and how many rest on a stored_history
span and are left as stored. --write applies the recomputed prices and moves, keeps each row's computation_version,
sets price_source (intrinio, or stored_history), and records a step outcome under STEP_LABEL.

Usage
-----
    python -m app.scripts.recompute_reactions_intrinio                 # dry run, every ticker
    python -m app.scripts.recompute_reactions_intrinio --symbols=MU,CAT
    python -m app.scripts.recompute_reactions_intrinio --write
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numpy as np
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.historical_reaction import SOURCE_INTRINIO, SOURCE_STORED_HISTORY
from app.scripts.compute_analyst_reactions import _compute_pre_market
from app.scripts.seed_historical_reactions import REFERENCE_SYMBOL, _build_date_cache, _compute, _compute_v3
from app.services import price_bars
from app.services.security_records import STORED_START
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Recompute reactions (Intrinio)"
TOLERANCE_PP = Decimal("0.01")
BARS_BATCH = 50          # symbols whose bars are read in one query
LARGEST = 10
VALUE_KEYS = {"earnings": ("close_before", "open_after", "close_after", "pct_change_1d", "pct_change_3d", "pct_change_5d", "volume_after"),
              "fomc": ("close_before", "open_after", "close_after", "pct_change_1d", "pct_change_3d", "pct_change_5d", "volume_after"),
              "analyst_action": ("close_before", "close_after", "pct_change_1d", "pct_change_5d")}


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    return v if isinstance(v, Decimal) else Decimal(str(round(float(v), 4)))


def classify(stored_1d, got_1d) -> str:
    """reproduced | filled | emptied | changed, on the one-day move."""
    s, g = _dec(stored_1d), _dec(got_1d)
    if s is None and g is None:
        return "reproduced"
    if s is None:
        return "filled"
    if g is None:
        return "emptied"
    return "reproduced" if abs(g - s) <= TOLERANCE_PP else "changed"


def recompute(row, hist, dates, sessions) -> dict | None:
    """The seeders' own computation for the row's event type; None when the bars cannot cover it."""
    etype, ed = row["event_type"], row["event_date"]
    try:
        if etype == "earnings":
            return _compute_v3(hist, dates, ed, row["report_timing"] or "unknown", sessions)
        if etype == "fomc":
            return _compute(hist, dates, ed, sessions)
        return _compute_pre_market(hist, dates, ed, sessions)
    except Exception:
        return None


@dataclass
class Tally:
    rows: int = 0
    reproduced: int = 0
    changed: int = 0
    filled: int = 0
    emptied: int = 0
    stored_history: int = 0
    no_bars: int = 0
    largest: list = field(default_factory=list)    # (delta, symbol, date, stored, got)

    def note(self, delta: Decimal, sym: str, d: date, s, g) -> None:
        self.largest.append((delta, sym, d.isoformat(), float(s), float(g)))
        self.largest.sort(key=lambda x: -x[0])
        del self.largest[LARGEST:]

    def summary(self) -> dict:
        return {"rows": self.rows, "reproduced": self.reproduced, "changed": self.changed, "filled": self.filled, "emptied": self.emptied,
                "stored_history": self.stored_history, "no_bars": self.no_bars,
                "largest": [{"delta_pp": float(d), "symbol": s, "date": dt, "stored_1d": a, "intrinio_1d": b} for d, s, dt, a, b in self.largest]}


def plan_update(row, got: dict | None) -> dict:
    """The columns --write sets for a non-stored-history row (None values clear the field)."""
    keys = VALUE_KEYS[row["event_type"]]
    out = {k: (got or {}).get(k) for k in keys}
    out["price_source"] = SOURCE_INTRINIO
    return out


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    only_set = {x.strip().upper() for x in only.split(",")} if only else None
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            select hr.id, t.symbol, hr.event_type::text as event_type, hr.event_date, hr.report_timing, hr.close_before, hr.open_after, hr.close_after,
                   hr.pct_change_1d, hr.pct_change_3d, hr.pct_change_5d, hr.computation_version, hr.price_source
            from historical_reactions hr join tickers t on t.id = hr.ticker_id order by t.symbol, hr.event_type, hr.event_date"""))).mappings().all()
    spy = price_bars.history_sync(REFERENCE_SYMBOL, STORED_START)          # one query; the session calendar
    if spy.empty:
        print(f"{STEP_LABEL}: no {REFERENCE_SYMBOL} bars stored; nothing can be computed")
        return 1
    sessions = _build_date_cache(spy)
    by: dict[str, list] = {}
    for r in rows:
        if only_set and r["symbol"] not in only_set:
            continue
        by.setdefault(r["symbol"], []).append(r)
    tallies = {t: Tally() for t in VALUE_KEYS}
    updates: list[dict] = []
    stored_marks: list = []
    records = price_bars.record_map_sync()                     # security_records once, not once per ticker
    symbols = sorted(by)
    frames: dict[str, object] = {}
    for i in range(0, len(symbols), BARS_BATCH):               # bars for many symbols per query
        frames.update(price_bars.bulk_bars_sync(symbols[i:i + BARS_BATCH], STORED_START))
    for sym in symbols:
        hist = frames.get(sym)
        dates = _build_date_cache(hist) if hist is not None and not hist.empty else np.array([])
        if hist is None:
            import pandas as pd
            hist = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        kept = records.stored_history_dates(sym, [r["event_date"] for r in by[sym]], sessions)
        for r in by[sym]:
            t = tallies[r["event_type"]]
            t.rows += 1
            if r["event_date"] in kept:
                t.stored_history += 1
                stored_marks.append(r["id"])
                continue
            got = recompute(r, hist, dates, sessions) if len(dates) else None
            if got is None and hist.empty:
                t.no_bars += 1
            kind = classify(r["pct_change_1d"], (got or {}).get("pct_change_1d"))
            setattr(t, kind, getattr(t, kind) + 1)
            if kind == "changed":
                t.note(abs(_dec(got["pct_change_1d"]) - _dec(r["pct_change_1d"])), sym, r["event_date"], r["pct_change_1d"], got["pct_change_1d"])
            updates.append({"id": r["id"], **plan_update(r, got)})
    # report
    print(f"\n{STEP_LABEL} ({'write' if write else 'dry run'}): {sum(t.rows for t in tallies.values())} row(s) over {len(by)} ticker(s)")
    print(f"  {'type':15} {'rows':>6} {'repro':>6} {'changed':>7} {'filled':>6} {'emptied':>7} {'stored':>6} {'no_bars':>7}")
    for name, t in tallies.items():
        print(f"  {name:15} {t.rows:6} {t.reproduced:6} {t.changed:7} {t.filled:6} {t.emptied:7} {t.stored_history:6} {t.no_bars:7}")
    print(f"  reproduced: one-day move within {TOLERANCE_PP} pp or both null; emptied: a stored value Intrinio has no bar for; stored: on a stored_history span, left as stored")
    for name, t in tallies.items():
        if t.largest:
            print(f"  ten largest changes, {name}:")
            for d, sym, dt, a, b in t.largest:
                print(f"    {sym:6} {dt} stored {a:+.4f} intrinio {b:+.4f} delta {float(d):.4f}")
    if write:
        async with ScriptSessionLocal() as s:
            for etype, keys in VALUE_KEYS.items():
                batch = [u for u in updates if set(u) == {"id", "price_source", *keys}]
                if not batch:
                    continue
                sets = ", ".join(f"{k} = :{k}" for k in keys)
                await s.execute(text(f"UPDATE historical_reactions SET {sets}, price_source = :price_source WHERE id = :id"), batch)
            if stored_marks:
                await s.execute(text("UPDATE historical_reactions SET price_source = :src WHERE id = ANY(:ids)"), {"src": SOURCE_STORED_HISTORY, "ids": stored_marks})
            await s.commit()
        print(f"  written: {len(updates)} row(s) recomputed and stamped {SOURCE_INTRINIO}, {len(stored_marks)} stamped {SOURCE_STORED_HISTORY}; computation_version kept")
        await record_step_fields(STEP_LABEL, {"tickers": len(by), "written": len(updates), "stored_history": len(stored_marks), "tolerance_pp": float(TOLERANCE_PP),
                                              "by_type": {n: t.summary() for n, t in tallies.items()}, "at": date.today().isoformat()})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
