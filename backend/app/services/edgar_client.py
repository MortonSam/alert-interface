"""SEC EDGAR client — filing search and company facts via public EDGAR API."""

from __future__ import annotations

from typing import Any

import httpx

EDGAR_BASE = "https://data.sec.gov"
# EDGAR requires a descriptive User-Agent per https://www.sec.gov/developer
USER_AGENT = "AlertInterface research@example.com"


class EdgarClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=EDGAR_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
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

    async def close(self) -> None:
        await self._client.aclose()
