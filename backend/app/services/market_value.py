"""A company's market value worked out from public sources (Sam, 2026-11-10): the shares outstanding on the cover page of its latest
10-Q or 10-K (dei:EntityCommonStockSharesOutstanding, every share class summed) times the licensed close (price_bars_shadow).
The vendor's market cap (tickers.market_cap) is personal-use data and is withheld from visitors.

SEC companyfacts carries only undimensioned facts, so a company with more than one class (Alphabet, Meta, Berkshire) has no
cover-page shares there; the cover's inline XBRL has every class, each in its own context on StatementClassOfStockAxis.
"""
from __future__ import annotations

import re
from datetime import date

FACT = "dei:EntityCommonStockSharesOutstanding"
CLASS_AXIS = "StatementClassOfStockAxis"
FORMS = ("10-Q", "10-K", "10-KT")

# A class worth a multiple of the listed class it is priced by: Berkshire's Class A converts into 1,500 Class B shares (BRK-B's
# close prices every class). Every other multi-class company in the index converts one for one.
CLASS_MULTIPLE = {"BRK-B": {"ClassA": 1500}}

# a member on the class axis that is not a class of common stock: a total (BlackRock's "FullyDilutedSharesMember"), units that
# exchange into shares, or preferred stock (Ares' mandatory convertible preferred)
NOT_A_CLASS = re.compile(r"FullyDiluted|Exchangeable|Preferred|Units?Member", re.I)

_CONTEXT = re.compile(r"<(?:\w+:)?context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:\w+:)?context>", re.S | re.I)
_MEMBER = re.compile(r"<(?:\w+:)?explicitMember\b[^>]*\bdimension=\"([^\"]+)\"[^>]*>\s*([^<\s]+)\s*<", re.S | re.I)
_INSTANT = re.compile(r"<(?:\w+:)?instant>\s*([0-9-]{10})\s*<", re.I)
_FACT = re.compile(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", re.S | re.I)
_ATTR = re.compile(r"([\w:.-]+)\s*=\s*\"([^\"]*)\"")
_TAG = re.compile(r"<[^>]+>")


def _value(attrs: dict, inner: str) -> float | None:
    """Pure: an ix:nonFraction's number, scaled; None when it can't be read."""
    fmt = attrs.get("format", "")
    text = _TAG.sub("", inner).strip()
    if "zero" in fmt or text in ("-", "—", "–"):
        return 0.0
    if "comma-decimal" in fmt or "numcommadecimal" in fmt.replace("-", ""):
        text = text.replace(".", "").replace(" ", "").replace(",", ".")
    else:
        text = text.replace(",", "").replace(" ", "")
    try:
        v = float(text)
    except ValueError:
        return None
    return v * 10 ** int(attrs.get("scale") or 0)


def cover_shares(html: str) -> dict | None:
    """Pure: the cover page's shares outstanding, {"as_of", "classes": [(member or "", shares)], "total"}, or None. Every class on
    the latest date is summed, each counted once; a context on any other axis (a co-registrant subsidiary's LegalEntityAxis) is not
    the company's. With no class contexts, the one undimensioned figure stands."""
    contexts = {}
    for cid, body in _CONTEXT.findall(html):
        inst = _INSTANT.search(body)
        contexts[cid] = {"dims": {d.split(":")[-1]: m.split(":")[-1] for d, m in _MEMBER.findall(body)}, "instant": inst.group(1) if inst else None}
    facts = []
    for raw_attrs, inner in _FACT.findall(html):
        attrs = dict(_ATTR.findall(raw_attrs))
        if attrs.get("name") != FACT:
            continue
        ctx = contexts.get(attrs.get("contextRef", ""))
        v = _value(attrs, inner)
        if not ctx or not ctx["instant"] or v is None:
            continue
        if any(axis != CLASS_AXIS for axis in ctx["dims"]) or NOT_A_CLASS.search(ctx["dims"].get(CLASS_AXIS, "")):
            continue
        facts.append((ctx["instant"], ctx["dims"].get(CLASS_AXIS, ""), v))
    if not facts:
        return None
    latest = max(f[0] for f in facts)
    on = [f for f in facts if f[0] == latest]
    by_class = {}
    for _, member, v in on:
        by_class.setdefault(member, v)
    classes = [(m, v) for m, v in by_class.items() if m] or [("", by_class[""])]
    return {"as_of": date.fromisoformat(latest), "classes": classes, "total": sum(v for _, v in classes)}


def priced_shares(symbol: str, cover: dict) -> float:
    """Pure: the cover's shares in units of the listed class the symbol's close prices (Berkshire's Class A at 1,500 Class B)."""
    mult = CLASS_MULTIPLE.get(symbol, {})
    return sum(v * next((k for name, k in mult.items() if name.lower() in m.lower()), 1) for m, v in cover["classes"])


def latest_cover_filing(submissions: dict) -> dict | None:
    """Pure: the newest 10-Q or 10-K in a submissions document, {accession, document, filed, form}."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    for i, form in enumerate(r.get("form", [])):
        if form in FORMS and r["primaryDocument"][i]:
            return {"accession": r["accessionNumber"][i], "document": r["primaryDocument"][i], "filed": r["filingDate"][i], "form": form}
    return None
