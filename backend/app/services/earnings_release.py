"""Whether an 8-K under Item 2.02 ("Results of Operations") is an earnings release.

Item 2.02 also carries releases that are not earnings: Tesla files its quarterly production and deliveries numbers under it
(Jan 2, Apr 2, Jul 2, Oct 2), and a company may pre-announce a figure or schedule a call. A filing counts as an earnings
release only when one of its exhibits states per-share results: a "per share" (or "per diluted share", "per unit", "EPS")
within PER_SHARE_WINDOW characters of a results word (net income, earnings, revenue, net sales, FFO, distributable earnings).
A release that states results without any per-share figure (Targa's Q2 2026 release) does not count; the calendar's other
evidence (Finnhub's and Yahoo's reported EPS) comes first.
"""
from __future__ import annotations

import re

PER_SHARE = re.compile(r"\bper\s+(?:diluted\s+|basic\s+|common\s+|weighted[\w\s-]{0,20}\s+)?share\b|\bper\s+(?:diluted|basic)\s+(?:common\s+)?unit\b|\bEPS\b", re.I)
RESULTS = re.compile(r"\b(net\s+(?:income|earnings|loss)|earnings|revenues?|net\s+sales|funds\s+from\s+operations|FFO|distributable\s+earnings)\b", re.I)
PER_SHARE_WINDOW = 200


def states_per_share_results(text: str) -> bool:
    """Pure: the text states a per-share result."""
    for m in PER_SHARE.finditer(text or ""):
        if RESULTS.search(text[max(0, m.start() - PER_SHARE_WINDOW): m.end() + PER_SHARE_WINDOW]):
            return True
    return False


async def is_earnings_release(edgar, cik: str, accession: str) -> bool:
    """An Item 2.02 filing is an earnings release when one of its documents states per-share results (the cover only names the
    item, so in practice the exhibit decides)."""
    from bs4 import BeautifulSoup
    for name in await edgar.list_filing_documents(cik, accession, every_exhibit=True):
        try:
            html = await edgar.fetch_filing_document(cik, accession, name)
        except Exception:
            continue
        if states_per_share_results(BeautifulSoup(html, "html.parser").get_text(" ")):
            return True
    return False
