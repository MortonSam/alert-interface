"""SEC EDGAR client — filing search and company facts via public EDGAR API."""

from __future__ import annotations
from app.services.redact import redact

import asyncio
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

EDGAR_BASE = "https://data.sec.gov"
SEC_BASE   = "https://www.sec.gov"
# EDGAR requires a descriptive User-Agent per https://www.sec.gov/developer
USER_AGENT = "AlertInterface research@example.com"

CACHE_DIR  = Path(__file__).parent / "cache"
CACHE_MAX_AGE_H = 24  # hours
SUBMISSIONS_CACHE_H = 6           # a filing index is reread after this long: fresh for each nightly, shared within a run
MIN_INTERVAL_S = 0.125            # at most 8 requests a second to the SEC (its limit is 10)
RETRY_DELAYS_S = (2.0, 5.0, 15.0) # after a 429 without a Retry-After header
_last_request_at = 0.0


def backoff_delay(attempt: int, retry_after: str | None) -> float | None:
    """Pure: how long to wait before retry `attempt` (0-based) after a 429: the Retry-After header's seconds when given, else
    the fixed ladder; None when no retry is left."""
    if attempt >= len(RETRY_DELAYS_S):
        return None
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass
    return RETRY_DELAYS_S[attempt]


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _cache_fresh(path: Path, max_age_h: float = CACHE_MAX_AGE_H) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) / 3600 < max_age_h


# Tickers whose filings sit under more than one CIK (predecessor first, current filer last): a reorganization moves the ticker to
# a new CIK and the earlier filings stay under the old one. Used by compute_pe (company facts) and backfill_report_timing (8-Ks).
# Never derive a predecessor from an accession prefix: that prefix names the submitter, often a filing agent, and Workiva Inc.
# (CIK 0001445305) files for its clients under its own CIK, so its calendar-quarter EPS once leaked into fifty tickers' quarters.
PREDECESSOR_CIKS: dict[str, list[str]] = {
    "XOM":  ["0000034088", "0002115436"],   # Exxon Mobil Corp -> ExxonMobil Holdings (files from 2026)
    "AVB":  ["0000915912"],   # AVALONBAY COMMUNITIES INC
    "EA":   ["0000712515"],   # ELECTRONIC ARTS INC
    "EQR":  ["0000906107"],   # EQUITY RESIDENTIAL
    "PSKY": ["0000813828", "0002041610"],   # Paramount Global -> Paramount Skydance Corp
    "BLK":  ["0001364742", "0002012383"],   # BlackRock Finance (old BlackRock) -> BlackRock, Inc.
    "BG":   ["0001144519", "0001996862"],   # Bunge Ltd -> Bunge Global SA
    "FERG": ["0001832433", "0002011641"],   # Ferguson plc -> Ferguson Enterprises Inc.
}


class EdgarClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=EDGAR_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        self._sec_client = httpx.AsyncClient(
            base_url=SEC_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

    async def _paced_get(self, client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
        """One SEC request at the paced rate; a 429 waits and retries up to len(RETRY_DELAYS_S) times, then raises."""
        import asyncio as _asyncio
        global _last_request_at
        attempt = 0
        while True:
            wait = MIN_INTERVAL_S - (time.time() - _last_request_at)
            if wait > 0:
                await _asyncio.sleep(wait)
            _last_request_at = time.time()
            resp = await client.get(url, **kw)
            if resp.status_code != 429:
                return resp
            delay = backoff_delay(attempt, resp.headers.get("Retry-After"))
            if delay is None:
                resp.raise_for_status()
            await _asyncio.sleep(delay)
            attempt += 1

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        """XBRL company facts — revenue, EPS, etc. CIK must be zero-padded to 10 digits. Cached on disk for CACHE_MAX_AGE_H:
        a document runs to several megabytes and the nightly reads hundreds."""
        import json as _json
        cache_file = _cache_path(f"companyfacts_{cik.zfill(10)}.json")
        if _cache_fresh(cache_file):
            try:
                return _json.loads(cache_file.read_text())
            except ValueError:
                pass
        resp = await self._paced_get(self._client, f"/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")
        resp.raise_for_status()
        cache_file.write_text(resp.text)
        return resp.json()

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        """Recent filing history for a CIK, cached SUBMISSIONS_CACHE_H hours."""
        import json as _json
        cache_file = _cache_path(f"submissions_{cik.zfill(10)}.json")
        if _cache_fresh(cache_file, SUBMISSIONS_CACHE_H):
            try:
                return _json.loads(cache_file.read_text())
            except ValueError:
                pass
        resp = await self._paced_get(self._client, f"/submissions/CIK{cik.zfill(10)}.json")
        resp.raise_for_status()
        cache_file.write_text(resp.text)
        return resp.json()

    # ── CIK lookup ────────────────────────────────────────────────────────────

    async def get_cik(self, symbol: str) -> str | None:
        """Map ticker symbol to zero-padded 10-digit CIK string."""
        cache_file = _cache_path("company_tickers.json")
        if _cache_fresh(cache_file):
            data = json.loads(cache_file.read_text())
        else:
            resp = await self._paced_get(self._sec_client, "/files/company_tickers.json")
            resp.raise_for_status()
            data = resp.json()
            try:
                cache_file.write_text(json.dumps(data))
            except OSError as exc:
                print(f"Warning: could not write CIK cache: {redact(exc)}", flush=True)

        upper = symbol.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == upper:
                return str(entry["cik_str"]).zfill(10)
        return None

    # ── 8-K retrieval with pagination ────────────────────────────────────────

    async def get_all_8k_records(self, cik: str) -> list[dict]:
        """Every 8-K for a CIK as {filing_date, acceptance, items, accession}.

        Follows filings.files pagination to get the complete history. `items`
        is EDGAR's comma-separated item list, e.g. "2.02,9.01" (earnings
        releases carry Item 2.02). The first 10 digits of `accession` identify
        the filer agent that submitted the document.
        """
        subs = await self.get_submissions(cik)
        filings = subs.get("filings", {})

        def _extract(recent: dict) -> list[dict]:
            forms = recent.get("form", [])
            n = len(forms)
            items = recent.get("items") or [""] * n
            accessions = recent.get("accessionNumber") or [""] * n
            docs = recent.get("primaryDocument") or [""] * n
            return [
                {"filing_date": fd, "acceptance": at, "items": it or "", "accession": acc or "", "primary_document": doc or ""}
                for form, fd, at, it, acc, doc in zip(
                    forms, recent.get("filingDate", []), recent.get("acceptanceDateTime", []), items, accessions, docs,
                )
                if form == "8-K"
            ]

        records = _extract(filings.get("recent", {}))
        for file_ref in filings.get("files", []):
            name = file_ref.get("name", "")
            if not name:
                continue
            try:
                resp = await self._paced_get(self._client, f"/submissions/{name}")
                resp.raise_for_status()
                records.extend(_extract(resp.json()))
            except Exception:
                continue
            await asyncio.sleep(0.12)
        return records

    async def get_all_8k_filings(self, cik: str) -> list[tuple[str, str, str]]:
        """Every 8-K for a CIK as (filing_date, acceptanceDateTime, items)."""
        return [(r["filing_date"], r["acceptance"], r["items"]) for r in await self.get_all_8k_records(cik)]

    # ── Filing discovery ─────────────────────────────────────────────────────

    async def get_best_filing(self, cik: str) -> dict[str, Any] | None:
        """Return metadata for most recent 10-Q, or 10-K if no 10-Q within 6 months."""
        subs = await self.get_submissions(cik)
        recent = subs.get("filings", {}).get("recent", {})

        forms      = recent.get("form", [])
        dates      = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs       = recent.get("primaryDocument", [])

        cutoff_6m = date.today() - timedelta(days=183)

        best_10q: dict | None = None
        best_10k: dict | None = None

        for form, filing_date_str, acc, doc in zip(forms, dates, accessions, docs):
            try:
                filing_date = date.fromisoformat(filing_date_str)
            except (ValueError, TypeError):
                continue

            entry = {
                "form_type": form,
                "filing_date": filing_date_str,
                "accession_number": acc,
                "primary_document": doc,
                "cik": cik,
            }

            if form == "10-Q" and best_10q is None:
                best_10q = entry
            elif form == "10-K" and best_10k is None:
                best_10k = entry

            # Once we have both candidates we can stop scanning
            if best_10q and best_10k:
                break

        if best_10q:
            # Use 10-K only if the most recent 10-Q is older than 6 months
            filing_date = date.fromisoformat(best_10q["filing_date"])
            if filing_date >= cutoff_6m:
                return best_10q
            if best_10k:
                return best_10k
            return best_10q  # stale 10-Q but no 10-K — use it anyway

        return best_10k  # None if no 10-K either

    # ── Filing document fetch ─────────────────────────────────────────────────

    async def fetch_filing_html(
        self, cik: str, accession_number: str, primary_document: str
    ) -> str:
        """Fetch the primary filing document HTML. Cached 24h by accession number."""
        safe_acc = accession_number.replace("-", "")
        cache_file = _cache_path(f"edgar_{accession_number}.html")

        if _cache_fresh(cache_file):
            return cache_file.read_text(encoding="utf-8", errors="replace")

        cik_int = str(int(cik))  # strip leading zeros: 0000320193 → 320193
        url = f"/Archives/edgar/data/{cik_int}/{safe_acc}/{primary_document}"
        resp = await self._paced_get(self._sec_client, url)
        resp.raise_for_status()
        html = resp.text
        try:
            cache_file.write_text(html, encoding="utf-8")
        except OSError as exc:
            print(f"Warning: could not cache filing {accession_number}: {redact(exc)}", flush=True)
        return html

    async def list_filing_documents(self, cik: str, accession_number: str) -> list[str]:
        """The .htm documents in a filing (the cover and its exhibits), from the filing's index. Cached 24h."""
        import json as _json
        safe_acc = accession_number.replace("-", "")
        cache_file = _cache_path(f"edgar_{accession_number}_index.json")
        if _cache_fresh(cache_file):
            data = _json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            resp = await self._paced_get(self._sec_client, f"/Archives/edgar/data/{int(cik)}/{safe_acc}/index.json")
            resp.raise_for_status()
            data = resp.json()
            try:
                cache_file.write_text(_json.dumps(data), encoding="utf-8")
            except OSError:
                pass
        names = [it.get("name", "") for it in data.get("directory", {}).get("item", [])]
        return [n for n in names if n.lower().endswith((".htm", ".html")) and not n.lower().startswith("r") or n.lower().startswith("ex")]

    async def fetch_filing_document(self, cik: str, accession_number: str, name: str) -> str:
        """One document of a filing (an exhibit, say), cached 24h by accession and name."""
        safe_acc = accession_number.replace("-", "")
        cache_file = _cache_path(f"edgar_{accession_number}_{name}")
        if _cache_fresh(cache_file):
            return cache_file.read_text(encoding="utf-8", errors="replace")
        resp = await self._paced_get(self._sec_client, f"/Archives/edgar/data/{int(cik)}/{safe_acc}/{name}")
        resp.raise_for_status()
        try:
            cache_file.write_text(resp.text, encoding="utf-8")
        except OSError:
            pass
        return resp.text

    async def filing_texts(self, cik: str, accession_number: str, primary_document: str) -> list[tuple[str, str]]:
        """(document name, plain text) for the cover and every exhibit of a filing; the cover first."""
        from bs4 import BeautifulSoup
        out = []
        try:
            html = await self.fetch_filing_html(cik, accession_number, primary_document)
            out.append((primary_document, BeautifulSoup(html, "html.parser").get_text(" ")))
        except Exception:
            pass
        try:
            for name in await self.list_filing_documents(cik, accession_number):
                if name == primary_document:
                    continue
                html = await self.fetch_filing_document(cik, accession_number, name)
                out.append((name, BeautifulSoup(html, "html.parser").get_text(" ")))
        except Exception:
            pass
        return out

    # ── Section extraction ───────────────────────────────────────────────────

    def extract_filing_sections(self, html: str) -> dict[str, str]:
        """Extract MD&A and Risk Factors sections from filing HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # Remove script/style noise
        for tag in soup(["script", "style", "table"]):
            tag.decompose()

        full_text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        text = "\n".join(lines)

        mda         = _extract_section(text, r"management.{0,10}discussion", r"quantitative|liquidity|market risk|item\s+3")
        risk_factors = _extract_section(text, r"risk factors", r"unresolved staff|properties|item\s+2")

        return {
            "mda":          mda[:4000] if mda else "",
            "risk_factors": risk_factors[:4000] if risk_factors else "",
        }

    # ── Convenience wrapper ───────────────────────────────────────────────────

    async def get_filing_text_for_ticker(
        self, symbol: str
    ) -> tuple[dict[str, Any], dict[str, str]] | None:
        """Return (filing_metadata, sections) or None if nothing found."""
        cik = await self.get_cik(symbol)
        if not cik:
            return None

        filing = await self.get_best_filing(cik)
        if not filing:
            return None

        html = await self.fetch_filing_html(
            cik=filing["cik"],
            accession_number=filing["accession_number"],
            primary_document=filing["primary_document"],
        )
        sections = self.extract_filing_sections(html)

        # Build public URL for source_filings record (Archives uses integer CIK, no leading zeros)
        safe_acc = filing["accession_number"].replace("-", "")
        cik_int = str(int(cik))
        filing["url"] = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}"
            f"/{safe_acc}/{filing['primary_document']}"
        )

        return filing, sections

    async def close(self) -> None:
        await self._client.aclose()
        await self._sec_client.aclose()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_section(text: str, start_pattern: str, end_pattern: str) -> str:
    """Extract text between a start heading and an end heading (case-insensitive)."""
    start_re = re.compile(start_pattern, re.IGNORECASE)
    end_re   = re.compile(end_pattern,   re.IGNORECASE)

    start_match = start_re.search(text)
    if not start_match:
        return ""

    remaining = text[start_match.start():]
    end_match = end_re.search(remaining, pos=len(start_match.group()))
    if end_match:
        return remaining[: end_match.start()].strip()
    # No end marker — return up to 5000 chars
    return remaining[:5000].strip()
