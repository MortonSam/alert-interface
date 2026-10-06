"""Dividend declarations from the earnings 8-K exhibits already fetched for EPS verification.

    parse_declaration(text, filing_date) -> {"amount", "payable_date", "record_date", "declared_on"} | None

The board's sentence has a stable shape: "declared a quarterly (cash) dividend of $0.15 per share, payable on October 29,
2026 to shareholders of record as of October 14, 2026". The filing date is declared_on. Under T+1 settlement the ex-dividend
date is the record date, so a declaration matches a stored ex-dividend event by record date.
"""
from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
_DATE = rf"(?:{_MONTHS})\.?\s+\d{{1,2}},\s+\d{{4}}"
_DECL = re.compile(
    rf"declared\s+(?:an?\s+)?(?:regular\s+)?(?:quarterly\s+)?(?:cash\s+)?dividend\s+of\s+\$\s?(?P<amount>\d+(?:\.\d+)?)\s+per\s+(?:common\s+)?share"
    rf"(?P<rest>.{{0,400}}?)(?=\.\s|\.$|$)", re.I | re.S)
_PAYABLE = re.compile(rf"payable\s+(?:in\s+cash\s+)?(?:on\s+|or\s+about\s+|on\s+or\s+about\s+)?(?P<d>{_DATE})", re.I)
_RECORD = re.compile(rf"record\s+(?:as\s+of\s+|on\s+|at\s+)?(?:the\s+close\s+of\s+business\s+(?:on\s+)?)?(?P<d>{_DATE})", re.I)


def _to_date(text: str) -> date | None:
    t = re.sub(r"\s+", " ", text.replace(".", "").replace("Sept ", "Sep ")).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def parse_declaration(text: str, filing_date: date) -> dict | None:
    """The declared per-share dividend with its payable and record dates, dated by the filing; None when the text declares none."""
    flat = re.sub(r"\s+", " ", text)
    for m in _DECL.finditer(flat):
        rest = m.group("rest")
        pay = _PAYABLE.search(rest)
        rec = _RECORD.search(rest)
        payable = _to_date(pay.group("d")) if pay else None
        record = _to_date(rec.group("d")) if rec else None
        if record is None and payable is None:
            continue
        return {"amount": float(m.group("amount")), "payable_date": payable, "record_date": record, "declared_on": filing_date}
    return None
