"""SEC EDGAR client — filing search and company facts via public EDGAR API."""

from __future__ import annotations

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


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _cache_fresh(path: Path, max_age_h: float = CACHE_MAX_AGE_H) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) / 3600 < max_age_h


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

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        """XBRL company facts — revenue, EPS, etc. CIK must be zero-padded to 10 digits."""
        resp = await self._client.get(f"/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")
        resp.raise_for_status()
        return resp.json()

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        """Recent filing history for a CIK."""
        resp = await self._client.get(f"/submissions/CIK{cik.zfill(10)}.json")
        resp.raise_for_status()
        return resp.json()

    # ── CIK lookup ────────────────────────────────────────────────────────────

    async def get_cik(self, symbol: str) -> str | None:
        """Map ticker symbol to zero-padded 10-digit CIK string."""
        cache_file = _cache_path("company_tickers.json")
        if _cache_fresh(cache_file):
            data = json.loads(cache_file.read_text())
        else:
            resp = await self._sec_client.get("/files/company_tickers.json")
            resp.raise_for_status()
            data = resp.json()
            try:
                cache_file.write_text(json.dumps(data))
            except OSError as exc:
                print(f"Warning: could not write CIK cache: {exc}", flush=True)

        upper = symbol.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == upper:
                return str(entry["cik_str"]).zfill(10)
        return None

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
        resp = await self._sec_client.get(url)
        resp.raise_for_status()
        html = resp.text
        try:
            cache_file.write_text(html, encoding="utf-8")
        except OSError as exc:
            print(f"Warning: could not cache filing {accession_number}: {exc}", flush=True)
        return html

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
