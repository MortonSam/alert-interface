"""Seed macro calendar events — CPI, NFP, and PPI releases.

FOMC decision days are not scraped here any more: services/fomc_calendar.py holds them as data and is the
only writer of "FOMC Meeting" events (two writers once produced two rows for one meeting); the nightly
validate check reads the Fed page and errors when the page and the module disagree.

Sources
-------

CPI / NFP / PPI:
        Primary  — FRED API release-dates endpoint (free key, set FRED_API_KEY
                   in .env).  Release IDs: CPI=10, Employment=50, PPI=237.
        Fallback — BLS website (https://www.bls.gov/schedule/news_release/).
                   BLS uses Akamai bot-detection; this may be blocked depending
                   on your network.  Set FRED_API_KEY for reliable operation.

Upserts match on (event_date, title) so re-runs are idempotent.

Usage
-----
    python -m app.scripts.seed_macro
    make seed-macro
"""

from __future__ import annotations

import asyncio
import sys
import re
from datetime import date, timedelta
from typing import NamedTuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import settings
from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event


# ── Constants ─────────────────────────────────────────────────────────────────

FRED_BASE = "https://api.stlouisfed.org/fred"
BLS_BASE  = "https://www.bls.gov/schedule/news_release"

# (human title, FRED release ID, BLS page filename)
BLS_RELEASES: list[tuple[str, int, str]] = [
    ("CPI Release",      10,  "cpi.htm"),
    ("Nonfarm Payrolls", 50,  "empsit.htm"),
    ("PPI Release",      46,  "ppi.htm"),
]

LOOKAHEAD_DAYS = 365  # seed up to one year ahead

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Domain type ───────────────────────────────────────────────────────────────

class MacroEvent(NamedTuple):
    event_date: date
    title: str
    source: DataSource


# ── FRED API ──────────────────────────────────────────────────────────────────

async def fetch_bls_via_fred(
    client: httpx.AsyncClient, api_key: str
) -> list[MacroEvent]:
    """Pull release dates for CPI, NFP, PPI from the FRED API."""
    today  = date.today()
    cutoff = today + timedelta(days=LOOKAHEAD_DAYS)
    events: list[MacroEvent] = []

    for title, release_id, _ in BLS_RELEASES:
        params = {
            "release_id": release_id,
            "api_key": api_key,
            "file_type": "json",
            # include_release_dates_with_no_data exposes BLS-scheduled future dates.
            # Sort descending so future dates come first; filter client-side for >= today.
            "include_release_dates_with_no_data": "true",
            "sort_order": "desc",
            "limit": 24,  # 24 months back + forward; future dates are at the top
        }
        try:
            resp = await client.get(
                f"{FRED_BASE}/release/dates", params=params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            batch = [
                MacroEvent(date.fromisoformat(item["date"]), title, DataSource.FRED)
                for item in data.get("release_dates", [])
                if today <= date.fromisoformat(item["date"]) <= cutoff
            ]
            print(f"  {title}: {len(batch)} dates  (FRED release {release_id})")
            events.extend(batch)
        except Exception as exc:
            print(f"  ERROR FRED release {release_id} ({title}): {exc}")

    return events


# ── BLS website fallback ──────────────────────────────────────────────────────

def _parse_bls_html(html: str, title: str) -> list[MacroEvent]:
    """
    BLS schedule pages list release dates in tables.
    Dates appear as plain text cells: 'January 14, 2026'
    """
    soup  = BeautifulSoup(html, "html.parser")
    today = date.today()
    cutoff = today + timedelta(days=LOOKAHEAD_DAYS)
    pattern = re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}")
    events: list[MacroEvent] = []

    for td in soup.find_all("td"):
        text = td.get_text(" ", strip=True)
        for raw in pattern.findall(text):
            try:
                from datetime import datetime
                d = datetime.strptime(raw, "%B %d, %Y").date()
                if today <= d <= cutoff:
                    events.append(MacroEvent(d, title, DataSource.MANUAL))
            except ValueError:
                pass

    return sorted(set(events))  # dedupe same-day duplicates from nested cells


async def upsert_macro_event(session, ev: MacroEvent) -> bool:
    """Upsert matching on (ticker_id IS NULL, event_date, title). Returns True if inserted."""
    existing = await session.scalar(
        select(Event).where(
            Event.ticker_id.is_(None),
            Event.event_date == ev.event_date,
            Event.title == ev.title,
        )
    )
    if existing:
        existing.source = ev.source
        return False

    session.add(Event(
        ticker_id=None,
        event_type=EventType.MACRO,
        event_date=ev.event_date,
        title=ev.title,
        source=ev.source,
        is_confirmed=True,
        metadata_={},
    ))
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

MACRO_STEP_LABEL = "Macro calendar (seed_macro)"    # the label in refresh.STEPS


async def main() -> int:
    all_events: list[MacroEvent] = []

    fred_key = (settings.fred_api_key or "").strip()
    if not fred_key:
        # fail closed: no scraping fallback; the step outcome names the missing key
        from app.services.step_outcomes import record_step_fields
        msg = "FRED_API_KEY is not set: the macro calendar is not refreshed"
        print(f"ERROR: {msg}", file=sys.stderr)
        await record_step_fields(MACRO_STEP_LABEL, {"error": msg})
        return 1

    async with httpx.AsyncClient() as client:
        print("\n── BLS Economic Releases ─────────────────────────────")
        print("  Using FRED API (key configured)")
        all_events.extend(await fetch_bls_via_fred(client, fred_key))

    if not all_events:
        print("\n⚠  No events found — nothing to upsert.")
        return 0

    print(f"\n── Upserting {len(all_events)} events ────────────────────────")
    inserted = updated = 0
    async with AsyncSessionLocal() as session:
        for ev in all_events:
            created = await upsert_macro_event(session, ev)
            if created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    print(f"  ✓ {inserted} inserted, {updated} updated")
    print("\n✓ Done.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
