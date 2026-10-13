"""Run validate checks once each, every one in its own READ ONLY transaction, and exit 1 if any check raises.

The push gate runs every check against alertdb_validate (the current schema with tests/fixtures/validate_fixture.sql loaded), so a query
Postgres cannot run (a parameter typed wrong, a string bound to a date) fails the gate instead of the nightly. Pointed at production it is
a read-only run of the named checks: nothing is written, not even fact_holds or step_outcomes.

    python -m app.scripts.validate_smoke [--url postgresql+asyncpg://...] [--checks check_a,check_b] [--show]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.scripts.validate_data import CHECKS
from app.services.redact import redact


def read_only_factory(url: str):
    """A session factory whose every session runs in a READ ONLY transaction and is rolled back."""
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)

    @asynccontextmanager
    async def session():
        async with maker() as s:
            await s.execute(text("SET TRANSACTION READ ONLY"))
            try:
                yield s
            finally:
                await s.rollback()
    return session


async def run(checks, url: str) -> list[tuple[str, object, str | None]]:
    """(check name, CheckResult or None, the exception's text or None) for each check, in order."""
    factory = read_only_factory(url)
    out = []
    for fn in checks:
        try:
            async with factory() as s:
                out.append((fn.__name__, await fn(s), None))
        except Exception as exc:
            out.append((fn.__name__, None, f"{type(exc).__name__}: {redact(exc)}"))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--checks", default="", help="comma-separated check function names; every check when omitted")
    ap.add_argument("--show", action="store_true", help="print each check's level, message and first rows")
    args = ap.parse_args(argv)
    names = [n for n in args.checks.split(",") if n]
    checks = [c for c in CHECKS if not names or c.__name__ in names]
    missing = set(names) - {c.__name__ for c in checks}
    if missing:
        print(f"no such check: {', '.join(sorted(missing))}", file=sys.stderr)
        return 2
    started = time.monotonic()
    results = asyncio.run(run(checks, args.url))
    raised = [(n, e) for n, _, e in results if e]
    for name, r, err in results:
        if err:
            print(f"RAISED  {name}: {err[:400]}")
        elif args.show:
            print(f"{r.level.upper():5}  {r.name}: {r.message}")
            for row in r.rows[:5]:
                print(f"         · {row}")
    print(f"{len(results)} check(s) run read only in {time.monotonic() - started:.1f}s; {len(raised)} raised")
    return 1 if raised else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
