"""Record why a company stopped trading, from its SEC filings: index_member false, inactive_reason, inactive_since, and an alias
when a successor ticker is stored (the old symbol then redirects to it). Dry run by default, in a READ ONLY transaction; --write applies.

EXITS holds only what the filings state, each fact with its accession number. A date no filing states stays None and is reported
as held. No EchoStar filing names the day SATS became ECHO; SATS is dated 2026-06-25, the first filing listing ECHO (Sam's rule,
2026-10-13), and its reason says so.

    python -m app.scripts.record_ticker_exits [--url postgresql+asyncpg://...]
    python -m app.scripts.record_ticker_exits --write
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.scripts.validate_smoke import read_only_factory
from app.services.ticker_exits import exit_kind, exit_line

EXITS = [
    {"symbol": "EA", "since": date(2026, 8, 4), "successor": None,
     "reason": "taken private on 2026-08-04: merged with Oak-Eagle MergerCo (owned by a consortium of PIF, Silver Lake and Affinity Partners) "
               "for $210 a share in cash; Nasdaq suspended trading before the open on 2026-08-05 "
               "(8-K 0001140361-26-031157; Form 25 0001354457-26-000757; Form 15 0001140361-26-032929)"},
    {"symbol": "AVB", "since": date(2026, 8, 17), "successor": "VMRK",
     "reason": "merged into VMRK on 2026-08-17: each AvalonBay share became 2.793 shares of Vivmark Residential (formerly Equity Residential); "
               "NYSE halted trading before the open on 2026-08-17 (8-K 0001104659-26-097833; Form 25 0000876661-26-000689)"},
    {"symbol": "SATS", "since": date(2026, 6, 25), "successor": "ECHO",
     "reason": "ticker changed to ECHO: EchoStar Corporation (CIK 1415404) still trades on Nasdaq; dated 2026-06-25, the first SEC filing "
               "listing ECHO (8-K 0001415404-26-000030), as no filing names the day of the change (the 8-K of 2026-06-18, "
               "0001415404-26-000027, still lists SATS); no Form 25 or Form 15 was filed"},
]


def plan_rows(stored: dict[str, dict], successors: dict[str, dict]) -> list[dict]:
    """Pure: what each exit changes. stored: {symbol: tickers row}; successors: {symbol: tickers row} for the successor symbols."""
    out = []
    for e in EXITS:
        row, sym = stored.get(e["symbol"]), e["symbol"]
        if row is None:
            out.append({"symbol": sym, "skip": "no tickers row"}); continue
        held = []
        succ = successors.get(e["successor"]) if e["successor"] else None
        if e["successor"] and (succ is None or not succ["is_active"]):
            held.append(f"successor {e['successor']} is not an active stored ticker: no alias")
        alias = None
        if succ is not None and succ["is_active"]:
            if e["since"] is None:
                held.append(f"no filing states the date {sym} became {e['successor']}: alias held (renamed_on is required)")
            else:
                alias = {"old_symbol": sym, "symbol": e["successor"], "renamed_on": e["since"], "reason": e["reason"]}
        if e["since"] is None:
            held.append("inactive_since held: no filing states the date")
        out.append({"symbol": sym, "set": {"index_member": False, "inactive_reason": e["reason"], "inactive_since": e["since"]},
                    "was": {k: row[k] for k in ("is_active", "index_member", "inactive_reason", "inactive_since")},
                    "alias": alias, "held": held, "kind": exit_kind(e["reason"]),
                    "line": exit_line(row["name"], e["reason"], e["since"])})
    return out


async def run(url: str, write: bool) -> int:
    factory = read_only_factory(url) if not write else async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)
    async with factory() as s:
        syms = [e["symbol"] for e in EXITS] + [e["successor"] for e in EXITS if e["successor"]]
        rows = {r.symbol: dict(r._mapping) for r in (await s.execute(text(
            "SELECT symbol, name, is_active, index_member, inactive_reason, inactive_since FROM tickers WHERE symbol = ANY(:s)"), {"s": syms})).all()}
        aliases = {r.old_symbol: dict(r._mapping) for r in (await s.execute(text(
            "SELECT old_symbol, symbol, renamed_on FROM ticker_aliases WHERE old_symbol = ANY(:s)"), {"s": syms})).all()}
        plans = plan_rows({e["symbol"]: rows[e["symbol"]] for e in EXITS if e["symbol"] in rows}, rows)
        print(f"record_ticker_exits ({'write' if write else 'dry run, read only'})")
        for p in plans:
            if p.get("skip"):
                print(f"  {p['symbol']}: skipped, {p['skip']}"); continue
            print(f"  {p['symbol']} ({p['kind']}): was {p['was']}")
            print(f"    set index_member=false, inactive_since={p['set']['inactive_since']}, inactive_reason={p['set']['inactive_reason']!r}")
            if p["alias"]:
                have = aliases.get(p["symbol"])
                note = f" (stored: -> {have['symbol']} on {have['renamed_on']})" if have else ""
                print(f"    alias {p['symbol']} -> {p['alias']['symbol']} renamed_on {p['alias']['renamed_on']}{note}")
            if p["line"]:
                print(f"    page line: {p['line']}")
            for h in p["held"]:
                print(f"    HELD: {h}")
            if write:
                await s.execute(text("UPDATE tickers SET index_member = false, inactive_reason = :r, inactive_since = :d WHERE symbol = :s"),
                                {"r": p["set"]["inactive_reason"], "d": p["set"]["inactive_since"], "s": p["symbol"]})
                if p["alias"]:
                    await s.execute(text("""INSERT INTO ticker_aliases (old_symbol, symbol, renamed_on, reason) VALUES (:o, :n, :d, :r)
                        ON CONFLICT (old_symbol) DO UPDATE SET symbol = EXCLUDED.symbol, renamed_on = EXCLUDED.renamed_on, reason = EXCLUDED.reason"""),
                                    {"o": p["alias"]["old_symbol"], "n": p["alias"]["symbol"], "d": p["alias"]["renamed_on"], "r": p["alias"]["reason"]})
        if write:
            await s.commit()
            print("  written")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    return asyncio.run(run(args.url, args.write))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
