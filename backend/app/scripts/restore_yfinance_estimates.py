"""Restore the near-term Yahoo Finance estimates the calendar step dropped on 2026-09-29.

The step's Yahoo pass ran out of its budget before the end of the alphabet and treated the tickers it
never reached as retracted, deleting their stored Yahoo estimates (UBER Nov 3, UNH Oct 13, ...). This
runs the calendar step's own fetch-decide-apply with no budgets: Finnhub's calendar, Yahoo Finance for
every active ticker, the announcement matcher for every ticker with a date within 60 days or a report
due. The rules that decide are the fixed ones (a silent source drops nothing; a nearer stored estimate
outranks a farther calendar date for the same quarter), so a Yahoo date is inserted as "estimated (Yahoo
Finance)" wherever no stored date lies within the quarterly cadence of it, a Finnhub placeholder for the
following quarter stays as the following estimate, and a company announcement confirms where one is found.

Usage
-----
    python -m app.scripts.restore_yfinance_estimates            # dry run: prints every change, writes nothing
    python -m app.scripts.restore_yfinance_estimates --write    # applies and records the step outcome
"""
from __future__ import annotations

import asyncio
import sys

from app.scripts.refresh_earnings_calendar import run

STEP_LABEL = "Restore Yahoo estimates (restore_yfinance_estimates)"


async def main(argv: list[str]) -> int:
    write = "--write" in argv
    print("Restore Yahoo Finance estimates: every active ticker, no budgets" + ("" if write else " (dry run)"))
    return await run(yf_budget_s=None, announce_budget_s=None, write=write, step_label=STEP_LABEL if write else None)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
