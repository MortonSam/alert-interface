"""Whether an 8-K under Item 2.02 ("Results of Operations") is an earnings release.

Item 2.02 also carries releases that are not earnings: Tesla files its quarterly production and deliveries numbers under it
(Jan 2, Apr 2, Jul 2, Oct 2), and a company may pre-announce a figure or schedule a call. A filing counts as an earnings
release only when one of its exhibits states per-share results: a "per share" (or "per diluted share", "per unit", "EPS")
within PER_SHARE_WINDOW characters of a results word (net income, earnings, revenue, net sales, FFO, distributable earnings).
A release that states results without any per-share figure (Targa's Q2 2026 release) does not count; the calendar's other
evidence (Finnhub's and Yahoo's reported EPS) comes first.

A filing that says the quarter's results are not final is a pre-announcement, never the results: AbbVie (Oct 5, 2026) and Regeneron
(Oct 6, 2026) filed Item 2.02 8-Ks naming an acquired IPR&D charge's per-share effect on a quarter whose "results ... have not been
finalized and are subject to ... financial statement closing procedures". Such a filing is not an earnings release whatever per-share
figures it states, so no step stores a report from it.
"""
from __future__ import annotations

import re

PER_SHARE = re.compile(r"\bper\s+(?:diluted\s+|basic\s+|common\s+|weighted[\w\s-]{0,20}\s+)?share\b|\bper\s+(?:diluted|basic)\s+(?:common\s+)?unit\b|\bEPS\b", re.I)
RESULTS = re.compile(r"\b(net\s+(?:income|earnings|loss)|earnings|revenues?|net\s+sales|funds\s+from\s+operations|FFO|distributable\s+earnings)\b", re.I)
PER_SHARE_WINDOW = 200
# "results ... have not been finalized" in one sentence (a purchase price allocation that "has not been finalized" in a merger's pro forma
# exhibit is not about results), or the period's "financial statement closing procedures" still to come
NOT_FINAL = re.compile(r"\bresults\b[^.]{0,120}?\b(?:(?:have|has)\s+not\s+(?:yet\s+)?been|(?:are|is)\s+not\s+yet)\s+finali[sz]ed\b"
                       r"|\bsubject\s+to\s+(?:the\s+completion\s+of\s+)?[\w\u2019'\s]{0,40}?financial\s+statement\s+closing\s+procedures\b", re.I)


def states_per_share_results(text: str) -> bool:
    """Pure: the text states a per-share result."""
    for m in PER_SHARE.finditer(text or ""):
        if RESULTS.search(text[max(0, m.start() - PER_SHARE_WINDOW): m.end() + PER_SHARE_WINDOW]):
            return True
    return False


def says_results_not_final(text: str) -> bool:
    """Pure: the text says the period's results are not final (a pre-announcement, not the results)."""
    return bool(NOT_FINAL.search(text or ""))


def is_results_release(texts: list[str]) -> bool:
    """Pure: a filing's documents report quarterly results: one states per-share results and none says the results are not final."""
    return any(states_per_share_results(t) for t in texts) and not any(says_results_not_final(t) for t in texts)


async def is_earnings_release(edgar, cik: str, accession: str) -> bool:
    """An Item 2.02 filing is an earnings release when one of its documents states per-share results (the cover only names the
    item, so in practice the exhibit decides) and none of them says the quarter's results are not yet final."""
    from bs4 import BeautifulSoup
    texts = []
    for name in await edgar.list_filing_documents(cik, accession, every_exhibit=True):
        try:
            html = await edgar.fetch_filing_document(cik, accession, name)
        except Exception:
            continue
        texts.append(BeautifulSoup(html, "html.parser").get_text(" "))
    return is_results_release(texts)
