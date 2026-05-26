"""Seed macro calendar events — FOMC meetings, CPI, NFP, and PPI releases.

Sources
-------
FOMC  : https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
        Scraped directly — no auth required. Uses the concluding day of each
        two-day meeting (i.e. the day the statement is released).

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
import re
from datetime import date, timedelta
from typing import NamedTuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event


# ── Constants ─────────────────────────────────────────────────────────────────

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
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


# ── FOMC scraper ──────────────────────────────────────────────────────────────

def _parse_fomc_html(html: str) -> list[MacroEvent]:
    """
    Parse upcoming FOMC meeting dates from the Fed's calendar page.

    HTML structure (stable since ~2018):
      <div class="panel-default">
        <h4><a id="42828">2026 FOMC Meetings</a></h4>
        ...
        <div class="row fomc-meeting">
          <div class="fomc-meeting__month ..."><strong>January</strong></div>
          <div class="fomc-meeting__date ...">27-28</div>   ← range; we take last day
        </div>
        ...
      </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    today  = date.today()
    cutoff = today + timedelta(days=LOOKAHEAD_DAYS)
    events: list[MacroEvent] = []

    for panel in soup.find_all("div", class_="panel-default"):
        heading = panel.find("h4")
        if not heading:
            continue
        m = re.search(r"(\d{4})\s+FOMC", heading.get_text())
        if not m:
            continue
        year = int(m.group(1))

        current_month: int | None = None
        for row in panel.find_all("div", class_="fomc-meeting"):
            month_div = row.find("div", class_="fomc-meeting__month")
            if month_div:
                name = month_div.get_text(strip=True).lower()
                current_month = MONTH_MAP.get(name)

            date_div = row.find("div", class_="fomc-meeting__date")
            if date_div and current_month:
                raw = date_div.get_text(strip=True).rstrip("*").strip()
                try:
                    # "27-28" → take end day; "28" → single day
                    day = int(raw.split("-")[-1])
                    d = date(year, current_month, day)
                    if today <= d <= cutoff:
                        events.append(MacroEvent(d, "FOMC Meeting", DataSource.FRED))
                except (ValueError, TypeError):
                    pass

    return sorted(events)


async def fetch_fomc(client: httpx.AsyncClient) -> list[MacroEvent]:
    print("\n── FOMC Meetings ─────────────────────────────────────")
    try:
        resp = await client.get(FOMC_URL, headers=_BROWSER_HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  ERROR: could not fetch Fed calendar — {exc}")
        return []

    events = _parse_fomc_html(resp.text)
    print(f"  Found {len(events)} upcoming meetings")
    for ev in events:
        print(f"    {ev.event_date}  {ev.title}")
    return events


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


async def fetch_bls_via_web(client: httpx.AsyncClient) -> list[MacroEvent]:
    """Try to scrape BLS directly. Akamai may block this — set FRED_API_KEY instead."""
    events: list[MacroEvent] = []
    for title, _, page in BLS_RELEASES:
        url = f"{BLS_BASE}/{page}"
        try:
            resp = await client.get(url, headers=_BROWSER_HEADERS, timeout=20)
            if resp.status_code != 200 or "Access Denied" in resp.text:
                print(
                    f"  ⚠  BLS blocked ({resp.status_code}) for '{title}'\n"
                    f"     Set FRED_API_KEY in .env for reliable access."
                )
                continue
            batch = _parse_bls_html(resp.text, title)
            print(f"  {title}: {len(batch)} dates  (BLS)")
            events.extend(batch)
        except Exception as exc:
            print(f"  ⚠  BLS fetch error for '{title}': {exc}")

    return events


# ── DB upsert ─────────────────────────────────────────────────────────────────

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

async def main() -> None:
    all_events: list[MacroEvent] = []

    async with httpx.AsyncClient() as client:
        all_events.extend(await fetch_fomc(client))

        print("\n── BLS Economic Releases ─────────────────────────────")
        fred_key = (settings.fred_api_key or "").strip()
        if fred_key:
            print(f"  Using FRED API (key configured)")
            all_events.extend(await fetch_bls_via_fred(client, fred_key))
        else:
            print("  FRED_API_KEY not set — trying BLS website (may be blocked by Akamai)")
            all_events.extend(await fetch_bls_via_web(client))

    if not all_events:
        print("\n⚠  No events found — nothing to upsert.")
        return

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


if __name__ == "__main__":
    asyncio.run(main())
