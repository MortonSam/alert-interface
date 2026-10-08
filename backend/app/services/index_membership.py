"""Who is in the S&P 500. The nightly scrape (Wikipedia, seed_sp500) proposes; a change takes effect only when a second source
agrees (the SPDR S&P 500 ETF's daily holdings file) or the scrape shows it two nights running. 2026-10-08: one scrape
deactivated CTVA and added VYLR the same night; both turned out right (SPY's Oct 7 holdings: Vylor in, Corteva out), but a
mid-edit table would have done the same. A scraped row whose CIK EDGAR assigns to a different stored ticker is an error that
changes nothing.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date

SPY_HOLDINGS_URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
SPY_MIN_HOLDINGS = 480        # a file with fewer equity rows is broken, not an index that shrank: it confirms nothing
PENDING_KEY = "index_membership_pending"


def parse_spy_holdings(xlsx: bytes) -> tuple[set[str], str | None]:
    """Pure: (the tickers in SPY's holdings file, "As of" text). Reads the sheet XML directly (no spreadsheet library)."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    strings = [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf-8"), re.S)]
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    tickers: set[str] = set()
    as_of = None
    in_table = False
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        vals: dict[str, str] = {}
        for col, attrs, v in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(?:<v>(.*?)</v>)?', row):
            if v is not None:
                vals[col] = strings[int(v)] if 't="s"' in attrs else v
        if vals.get("A") == "Holdings:":
            as_of = vals.get("B")
        if vals.get("A") == "Name" and vals.get("B") == "Ticker":
            in_table = True
            continue
        if in_table and vals.get("B") and vals.get("B") != "-" and re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", vals["B"]):
            tickers.add(vals["B"].replace(".", "-"))
    return tickers, as_of


async def fetch_spy_holdings() -> tuple[set[str] | None, str]:
    """(SPY's tickers, a note), or (None, why) when the file cannot be read or is too short to confirm anything."""
    import httpx
    try:
        r = httpx.get(SPY_HOLDINGS_URL, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=30)
        r.raise_for_status()
        held, as_of = parse_spy_holdings(r.content)
    except Exception as exc:          # a failed second source confirms nothing; the two-night rule still applies
        return None, f"SPY holdings unreadable ({type(exc).__name__})"
    if len(held) < SPY_MIN_HOLDINGS:
        return None, f"SPY holdings file has only {len(held)} tickers"
    return held, f"SPY holdings {as_of or 'undated'}"


@dataclass
class Decision:
    leave: list[str] = field(default_factory=list)          # take effect tonight
    join: list[str] = field(default_factory=list)
    pending_leave: dict[str, str] = field(default_factory=dict)   # {symbol: first night missing}, waiting for a second night or SPY
    pending_join: dict[str, str] = field(default_factory=dict)
    why: dict[str, str] = field(default_factory=dict)


def decide(scraped: set[str], active: set[str], spy: set[str] | None, pending: dict, today: date) -> Decision:
    """Pure: which scraped changes take effect. A leaver (active, not scraped) leaves when SPY lacks it too or it was already missing
    on the previous run; a joiner (scraped, not active) joins when SPY holds it or it was already new on the previous run. Anything
    else waits in `pending`, which keeps only tonight's candidates (a name back on the list resets)."""
    d = Decision()
    prev_leave, prev_join = pending.get("leave", {}), pending.get("join", {})
    for sym in sorted(active - scraped):
        if spy is not None and sym not in spy:
            d.leave.append(sym); d.why[sym] = "missing from the constituent list and from SPY's holdings"
        elif sym in prev_leave and prev_leave[sym] < today.isoformat():
            d.leave.append(sym); d.why[sym] = f"missing from the constituent list since {prev_leave[sym]} (two nights)"
        else:
            d.pending_leave[sym] = prev_leave.get(sym, today.isoformat())
            d.why[sym] = "missing from the constituent list" + (", but SPY still holds it" if spy is not None else "; waiting for a second night")
    for sym in sorted(scraped - active):
        if spy is not None and sym in spy:
            d.join.append(sym); d.why[sym] = "new on the constituent list and in SPY's holdings"
        elif sym in prev_join and prev_join[sym] < today.isoformat():
            d.join.append(sym); d.why[sym] = f"new on the constituent list since {prev_join[sym]} (two nights)"
        else:
            d.pending_join[sym] = prev_join.get(sym, today.isoformat())
            d.why[sym] = "new on the constituent list" + (", but not in SPY's holdings" if spy is not None else "; waiting for a second night")
    return d


def cik_conflicts(rows: list[dict], owners: dict[str, set[str]], stored: set[str]) -> dict[str, str]:
    """Pure: {symbol: why} for scraped rows whose CIK EDGAR assigns to a different stored ticker and not to the row's own symbol (a
    misparse or a mid-edit table). Share classes (GOOG and GOOGL under one CIK) pass: EDGAR lists both."""
    out: dict[str, str] = {}
    for r in rows:
        cik = re.sub(r"\D", "", r.get("cik") or "").zfill(10) if r.get("cik") else None
        if not cik or cik == "0000000000":
            continue
        own = owners.get(cik, set())
        others = (own & stored) - {r["symbol"]}
        if own and r["symbol"] not in own and others:
            out[r["symbol"]] = f"CIK {cik} belongs to {', '.join(sorted(others))}, not {r['symbol']}"
    return out
