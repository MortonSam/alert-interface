"""Score expected report windows against the company-confirmed report dates stored on 2026-10-13 (tests/fixtures).

The fixture holds every future earnings date a company's own words confirmed (events source edgar, is_confirmed), read from
production. A window contains a date when start <= date <= end. The pass mark: at least PASS_CONTAINED contained, and each of
NAMED contained. CL, EMR and FERG are named too but have no company-confirmed date stored, so they are reported as unmeasured.

    python -m app.scripts.score_report_windows                    # the windows stored by the last windows step
    python -m app.scripts.score_report_windows --from-verdicts    # windows recomputed from the stored filing verdicts, today 2026-10-13
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import report_windows as W

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "confirmed_report_dates_2026-10-13.csv"
FIXTURE_DAY = date(2026, 10, 13)
PASS_CONTAINED = 90
NAMED = ("HAL", "KIM", "KKR", "CL", "EMR", "FERG", "FDX")


def load_fixture() -> dict[str, date]:
    with open(FIXTURE, newline="") as fh:
        return {r["symbol"]: date.fromisoformat(r["date"]) for r in csv.DictReader(fh)}


def score(confirmed: dict[str, date], windows: dict[str, dict | None]) -> dict:
    """Pure: {contained, total, misses [(symbol, date, window or None)], named {symbol: True | False | None}, passed}."""
    misses = []
    for sym, d in sorted(confirmed.items()):
        w = windows.get(sym)
        if not w or not (date.fromisoformat(str(w["start"])) <= d <= date.fromisoformat(str(w["end"]))):
            misses.append((sym, d.isoformat(), f"{w['start']}..{w['end']}" if w else None))
    missed = {m[0] for m in misses}
    named = {s: (None if s not in confirmed else s not in missed) for s in NAMED}
    contained = len(confirmed) - len(misses)
    return {"contained": contained, "total": len(confirmed), "misses": misses, "named": named,
            "passed": contained >= PASS_CONTAINED and all(v is not False for v in named.values())}


async def stored_windows(symbols: list[str]) -> dict[str, dict | None]:
    async with ScriptSessionLocal() as s:
        rows = dict((await s.execute(text("SELECT key, value FROM system_metadata WHERE key = ANY(:k)"),
                                     {"k": [W.KEY.format(sym=x) for x in symbols]})).all())
    return {x: W.window_from_record(rows.get(W.KEY.format(sym=x))) for x in symbols}


async def verdict_windows(symbols: list[str], today: date) -> dict[str, dict | None]:
    """Each symbol's window recomputed from its stored filing verdicts (no SEC request), as the step would on `today`."""
    async with ScriptSessionLocal() as s:
        rows = dict((await s.execute(text("SELECT key, value FROM system_metadata WHERE key = ANY(:k)"),
                                     {"k": [W.VERDICTS_KEY.format(sym=x) for x in symbols]})).all())
    out = {}
    for x in symbols:
        judged = json.loads(rows.get(W.VERDICTS_KEY.format(sym=x)) or "{}")
        dates = [date.fromisoformat(v["filed"]) for v in judged.values() if v.get("earnings")]
        w = W.expected_window(x, dates, today)
        out[x] = w.as_record() if w else None
    return out


async def run(argv: list[str]) -> int:
    confirmed = load_fixture()
    syms = sorted(confirmed)
    windows = await (verdict_windows(syms, FIXTURE_DAY) if "--from-verdicts" in argv else stored_windows(syms))
    r = score(confirmed, windows)
    print(f"contained {r['contained']} of {r['total']} (pass mark {PASS_CONTAINED}); named: "
          + ", ".join(f"{s} {'in' if v else 'OUT' if v is False else 'no confirmed date stored'}" for s, v in r["named"].items()))
    for m in r["misses"]:
        print(f"  miss {m[0]} {m[1]}: window {m[2] or 'none'}")
    print("PASS" if r["passed"] else "FAIL")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
