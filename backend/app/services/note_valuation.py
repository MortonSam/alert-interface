"""What a served research note may say (2026-10-15).

1. Valuation multiples follow the site's P/E hold. While PE_ENABLED is off a visitor sees no P/E or other multiple anywhere in a
   note: points and Bottom Line sentences that name one are dropped, as are verification claims that name one, the multiple fields of
   the financials block, and sentences of an older markdown note.
2. A note never states a figure the Overview states for the same fact. The Overview's market value is the latest quote times the
   shares outstanding, dated, and shown only where it agrees with the dated market cap on file; a note's market cap is the figure at
   the hour it was written. The served note drops its market cap stat and every sentence that states a market cap figure, so the
   page shows one market value, the Overview's (VMRK's note said $47.32B beside an Overview of $23 billion on 2026-10-15).
3. A note states no beat rate and no move after past reports (Sam, 2026-10-19): the stats strip's "EPS beats 10/20" and "Latest Move
   -14.5% post-earnings 1d" are dropped as served; the ticker page's Evidence holds the past reports.

Applied at serve time to stored notes (routers/research_notes), so no stored note is rewritten.
"""
from __future__ import annotations

import re

VALUATION = re.compile(
    r"\bP\s?/\s?E\b|\bPE ratio|price[- /]to[- ]earnings|price/earnings|earnings multiple|\bmultiples?\b|\bEV\s?/\s?(?:EBITDA|sales|revenue)"
    r"|price[- /]to[- ](?:sales|book|free cash flow|cash flow)|\bP\s?/\s?[SB]\b|\bPEG\b|\btimes (?:forward |trailing )?(?:earnings|sales|EBITDA)"
    r"|\b\d+(?:\.\d+)?\s?x (?:forward |trailing )?(?:earnings|sales|EBITDA|revenue)", re.I)
MARKET_CAP_FIGURE = re.compile(r"market (?:cap(?:italization)?|value)[^.]{0,60}?\$\s?\d|\$\s?\d[\d.,]*\s?(?:[BMT]|billion|trillion|million)\b[^.]{0,30}market (?:cap|value)", re.I)
VALUATION_FIELDS = ("pe_ttm", "forward_pe", "peg_ttm", "ps_ttm", "pb", "ev_ebitda", "pe_percentile", "pe_sector_median")
OVERVIEW_STATS = ("market_cap",)
PAST_REPORT_STATS = ("beat_count", "total_quarters", "quarters_with_data", "quarters_without_data", "basis_excluded", "unavailable_reason",
                     "latest_move_1d", "latest_outcome")
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _drop(text: str | None, *patterns: re.Pattern) -> str | None:
    if not text:
        return text
    return " ".join(x for x in _SENTENCES.split(text) if x and not any(p.search(x) for p in patterns))


def served(structured: dict | None, verification: dict | None, content: str | None, valuation_shown: bool) -> tuple[dict | None, dict | None, str | None]:
    """Pure: (structured, verification, content) as a visitor may see them. Verification totals are recounted by the caller."""
    pats = (MARKET_CAP_FIGURE,) if valuation_shown else (MARKET_CAP_FIGURE, VALUATION)
    if structured:
        s = dict(structured)
        for sec in ("highlights", "watch", "risks"):
            s[sec] = [p for p in (s.get(sec) or []) if not any(x.search(f"{p.get('lead', '')} {p.get('detail', '')}") for x in pats)]
        s["bottom_line"] = _drop(s.get("bottom_line"), *pats) or ""
        if isinstance(s.get("stats"), dict):
            s["stats"] = {k: (None if k in OVERVIEW_STATS or k in PAST_REPORT_STATS else v) for k, v in s["stats"].items()}
        if not valuation_shown and isinstance(s.get("financials"), dict):
            s["financials"] = {k: v for k, v in s["financials"].items() if k not in VALUATION_FIELDS}
        structured = s
    if verification and isinstance(verification.get("claims"), list):
        verification = {**verification, "claims": [c for c in verification["claims"] if isinstance(c, dict) and not any(
            x.search(str(c.get(k) or "")) for x in pats for k in ("claim", "reason", "evidence"))]}
    content = _drop(content, *pats)
    return structured, verification, content


def leaks(structured: dict | None, verification: dict | None, content: str | None, valuation_shown: bool) -> list[str]:
    """Pure: every place a served note still names a multiple (while they are held), a market cap figure, a beat rate or a move after
    past reports (the stats strip); empty when clean."""
    out = [f"past-report stat: {k}" for k in ("beat_count", "latest_move_1d")
           if structured and isinstance(structured.get("stats"), dict) and structured["stats"].get(k) is not None]
    texts = [content or ""]
    if structured:
        texts += [f"{p.get('lead', '')} {p.get('detail', '')}" for sec in ("highlights", "watch", "risks") for p in (structured.get(sec) or [])]
        texts.append(structured.get("bottom_line") or "")
    if verification:
        texts += [str(c.get("claim") or "") for c in verification.get("claims") or [] if isinstance(c, dict)]
    pats = [("market cap figure", MARKET_CAP_FIGURE)] + ([] if valuation_shown else [("valuation multiple", VALUATION)])
    return out + [f"{name}: {t[:120]}" for t in texts for name, p in pats if p.search(t)]
