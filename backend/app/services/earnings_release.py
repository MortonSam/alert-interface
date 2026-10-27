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

A filing whose headline or Item 2.02 / 7.01 paragraph calls its figures preliminary, or that announces a change in its method of
accounting, is not the results either (2026-10-27; validate's five phantom reports): Kimberly-Clark's "Preliminary Third Quarter 2026
Results ... Final Third Quarter ... results to be Released November 5", Prudential's "certain preliminary financial information", UDR's
"preliminary financial results", Emerson's pension accounting change with its recast history, and Cencora's outlook update "between
now and the time financial results for the full-year 2026 are finalized". Only the headline and the item paragraphs are read for
"preliminary": General Dynamics heads its results tables "Preliminary Financial Information" and Western Digital's boilerplate calls
its own results preliminary. Over the 3,885 releases cached on 2026-10-27 the rule turns away 14, every one a pre-announcement
(Boeing's, A. O. Smith's, Starbucks', Supermicro's, Hormel's ...) except ADM's delayed Q3 2024 report, which named itself preliminary.
"""
from __future__ import annotations

import re

PER_SHARE = re.compile(r"\bper\s+(?:diluted\s+|basic\s+|common\s+|weighted[\w\s-]{0,20}\s+)?share\b|\bper\s+(?:diluted|basic)\s+(?:common\s+)?unit\b|\bEPS\b", re.I)
RESULTS = re.compile(r"\b(net\s+(?:income|earnings|loss)|earnings|revenues?|net\s+sales|funds\s+from\s+operations|FFO|distributable\s+earnings)\b", re.I)
PER_SHARE_WINDOW = 200
# "results ... have not been finalized" in one sentence (a purchase price allocation that "has not been finalized" in a merger's pro forma
# exhibit is not about results), or the period's "financial statement closing procedures" still to come
NOT_FINAL = re.compile(r"\bresults\b[^.]{0,120}?\b(?:(?:have|has)\s+not\s+(?:yet\s+)?been|(?:are|is)\s+not\s+yet)\s+finali[sz]ed\b"
                       r"|\bsubject\s+to\s+(?:the\s+completion\s+of\s+)?[\w\u2019'\s]{0,40}?financial\s+statement\s+closing\s+procedures\b"
                       r"|\btime\s+(?:the\s+)?(?:financial\s+)?results\b[^.]{0,60}?\bare\s+finali[sz]ed\b", re.I)
# read only in the lead (LEAD_CHARS) and the Item 2.02 / 7.01 paragraphs (ITEM_CHARS after each)
PRELIMINARY = re.compile(r"\bpreliminary\s+(?:(?:unaudited\s+)?(?:first|second|third|fourth)\s+quarter(?:\s+(?:and\s+)?(?:full[- ]year|fiscal))?(?:\s+\d{4})?"
                         r"\s+(?:financial\s+)?results|(?:unaudited\s+)?(?:financial\s+)?results\s+for\s+the\s+(?:quarter|three\s+months)"
                         r"|financial\s+(?:information|data|results)\b|estimates\s+of\s+certain\s+financial)"
                         r"|\bchange\s+(?:in\s+)?its\s+(?:method|policy)\s+of\s+accounting\b", re.I)
ITEM = re.compile(r"\bItem\s+(?:2\.02|7\.01)\b", re.I)
LEAD_CHARS, ITEM_CHARS = 1000, 600


def states_per_share_results(text: str) -> bool:
    """Pure: the text states a per-share result."""
    for m in PER_SHARE.finditer(text or ""):
        if RESULTS.search(text[max(0, m.start() - PER_SHARE_WINDOW): m.end() + PER_SHARE_WINDOW]):
            return True
    return False


def says_results_not_final(text: str) -> bool:
    """Pure: the text says the period's results are not final (a pre-announcement, not the results)."""
    return bool(NOT_FINAL.search(text or ""))


def says_preliminary(text: str) -> bool:
    """Pure: the text's headline or Item 2.02 / 7.01 paragraph calls its figures preliminary or announces an accounting change."""
    t = text or ""
    lead = " | ".join([t[:LEAD_CHARS]] + [t[m.end():m.end() + ITEM_CHARS] for m in ITEM.finditer(t)])
    return bool(PRELIMINARY.search(lead))


def is_results_release(texts: list[str]) -> bool:
    """Pure: a filing's documents report quarterly results: one states per-share results, none says the results are not final and
    none calls itself preliminary."""
    return (any(states_per_share_results(t) for t in texts)
            and not any(says_results_not_final(t) or says_preliminary(t) for t in texts))


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
