"""The company's own description of its business, Item 1 of its latest 10-K, as evidence for the research note's verifier (Sam,
2026-10-28). The note's What they do line drew on general knowledge the verifier had no source for, so it was marked unsupported
(BNY's revenue mix and rate sensitivity); with Item 1 in its evidence the verifier can confirm or reject it, and the generator reads the
same text.

Item 1 is read as Ivy's walkthrough reads it (risk_factors.item_1): the longest span from an "Item 1 ... Business" heading to Item 1A,
its plain paragraphs, the first EVIDENCE_CHARS of them.
"""
from __future__ import annotations

from app.services.redact import redact

EVIDENCE_CHARS = 8000
ANNUAL_FORMS = ("10-K", "10-KT", "10-K405")


def latest_annual(submissions: dict) -> dict | None:
    """Pure: the latest 10-K in a submissions record: {accession, filed, primary_document, form}, or None."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    for i, form in enumerate(r.get("form") or []):
        if form in ANNUAL_FORMS:
            return {"accession": r["accessionNumber"][i], "filed": r["filingDate"][i], "primary_document": r["primaryDocument"][i], "form": form}
    return None


async def business_section(edgar, symbol: str) -> dict | None:
    """{form, filed, accession, text} for the latest 10-K's Item 1, or None when there is no 10-K or no Item 1 could be read. Never
    raises: a failed fetch is printed and the note is checked without it."""
    from app.services.risk_factors import blocks, item_1
    try:
        cik = await edgar.get_cik(symbol)
        k = latest_annual(await edgar.get_submissions(cik)) if cik else None
        if not k:
            return None
        text = item_1(blocks(await edgar.fetch_filing_html(cik, k["accession"], k["primary_document"])), chars=EVIDENCE_CHARS)
    except Exception as exc:
        print(f"Item 1 fetch failed for {symbol}: {redact(exc)}", flush=True)
        return None
    return {**k, "text": text} if text else None
