"""A company's market value worked out from public sources (Sam, 2026-11-10): the shares outstanding on the cover page of its latest
10-Q or 10-K (dei:EntityCommonStockSharesOutstanding), each share class times its own licensed close (price_bars_shadow), one
figure per company (company_value; stored dated in market_values by scripts/compute_market_values, read through
services/market_value_store). The vendor's market cap (tickers.market_cap) is personal-use data and is withheld from visitors;
a company on the hold-out list (HELD) shows no figure at all, never the vendor's.

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

MARKET_VALUE_VERSION = 1
MAX_CLOSE_LAG_DAYS = 7          # a symbol whose newest close is this many days behind the newest close on file prices nothing

# A company with more than one class listed in the index: each class on the cover is priced by its own listed symbol's close, and
# every one of its symbols carries the company's one figure. The key is the company's symbol in market_values.company. An unlisted
# class is priced by the listed class it converts into one for one (Alphabet's Class B into Class A).
LISTED_CLASSES = {
    "GOOGL": {"ClassA": "GOOGL", "ClassB": "GOOGL", "ClassC": "GOOG"},
    "FOXA": {"ClassA": "FOXA", "ClassB": "FOX"},
    "NWSA": {"ClassA": "NWSA", "ClassB": "NWS"},
}
COMPANY = {sym: key for key, classes in LISTED_CLASSES.items() for sym in classes.values()}

# The hold-out list (Sam, 2026-11-10): cover-page shares times the close is not the company's market value for these, so they
# show no figure and are left out of the index-share line. symbol -> (reason, the cover date it was held on): with a date, the
# hold lifts when a cover dated after it is on file; with None it stands until the name is taken off this list.
MERGER = "shares were issued in a merger after the cover date"
STRUCTURE = "a holding-company structure: the cover's classes are not the economic share count"
UNEXPLAINED = "the cover's share count differs from the vendor's by more than 3%, unexplained"
CONVERSION = "the conversion ratios of its class B and class C shares are not applied"
OLD_COVER = "the cover page is old"
NO_COVER = "no 10-Q or 10-K cover on file"
SPLIT = "a stock split after the cover date"
NO_CLOSE = "no recent close on file for a class on the cover"
UNPRICED_CLASS = "a class on the cover has no listed symbol to price it"
HELD: dict[str, tuple[str, date | None]] = {
    "KMB": (MERGER, date(2026, 10, 29)), "CHTR": (MERGER, date(2026, 9, 30)), "FOX": (MERGER, date(2026, 10, 28)), "FOXA": (MERGER, date(2026, 10, 28)),
    "IBKR": (STRUCTURE, None), "BX": (STRUCTURE, None), "ARES": (STRUCTURE, None),
    "PCG": (UNEXPLAINED, None), "ACN": (UNEXPLAINED, None), "MPC": (UNEXPLAINED, None), "APA": (UNEXPLAINED, None), "DVN": (UNEXPLAINED, None),
    "CF": (UNEXPLAINED, None),
    "V": (CONVERSION, None),
    "LULU": (OLD_COVER, date(2026, 8, 28)), "DHI": (OLD_COVER, date(2026, 7, 16)), "P": (OLD_COVER, date(2026, 8, 31)), "APD": (OLD_COVER, date(2026, 6, 30)),
    "BDX": (OLD_COVER, date(2026, 6, 30)), "JCI": (OLD_COVER, date(2026, 6, 30)), "ROK": (OLD_COVER, date(2026, 6, 30)), "TSN": (OLD_COVER, date(2026, 6, 27)),
}

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


def fresh_closes(closes: dict[str, tuple[date, float]]) -> dict[str, tuple[date, float]]:
    """Pure: the closes no more than MAX_CLOSE_LAG_DAYS behind the newest one on file, so a halted or delisted symbol's old close
    never prices a figure dated as today's."""
    newest = max((day for day, _ in closes.values()), default=None)
    return {s: (day, close) for s, (day, close) in closes.items() if (newest - day).days <= MAX_CLOSE_LAG_DAYS}


def company_of(symbol: str) -> str:
    """Pure: the symbol a company's one figure is keyed by (GOOG and GOOGL are both GOOGL); a one-symbol company is its own."""
    return COMPANY.get(symbol, symbol)


def company_symbols(symbol: str) -> list[str]:
    """Pure: every listed symbol of the symbol's company, the key first."""
    key = company_of(symbol)
    return [key] + sorted({s for s in LISTED_CLASSES.get(key, {}).values() if s != key})


def held_reason(symbol: str, cover: dict | None) -> str | None:
    """Pure: why the symbol's company is on the hold-out list today, or None. A dated hold lifts once the cover on file is dated
    after the one it was held on."""
    for sym in company_symbols(symbol):
        if sym in HELD:
            reason, held_on = HELD[sym]
            if held_on is None or cover is None or cover["as_of"] <= held_on:
                return reason
    return None


def company_value(symbol: str, cover: dict | None, closes: dict[str, tuple[date, float]], split_after: date | None = None) -> dict:
    """Pure: the company's one market value, each class on the cover times its own close:
    {"company", "value" (None when held), "held_reason", "shares" (in units of the listed classes), "shares_as_of", "close_date"
    (the oldest close used), "classes": [{"member", "shares", "priced_by", "multiple", "close", "close_date"}]}.
    closes is {symbol: (date, close)}, the latest licensed close of each listed symbol; split_after is a split dated after the
    cover, whose share count the cover does not carry. A class with no shares needs no price."""
    key = company_of(symbol)
    out = {"company": key, "value": None, "held_reason": None, "shares": None, "shares_as_of": cover["as_of"] if cover else None, "close_date": None, "classes": []}
    if cover is None:
        return {**out, "held_reason": NO_COVER}
    listed, mult = LISTED_CLASSES.get(key), CLASS_MULTIPLE.get(key, {})
    reason = held_reason(key, cover) or (SPLIT if split_after and split_after > cover["as_of"] else None)
    for member, shares in cover["classes"]:
        priced_by = next((s for name, s in listed.items() if name.lower() in member.lower()), None) if listed else key
        k = next((v for name, v in mult.items() if name.lower() in member.lower()), 1)
        day, close = closes.get(priced_by) or (None, None) if priced_by else (None, None)
        out["classes"].append({"member": member, "shares": shares, "priced_by": priced_by, "multiple": k, "close": close, "close_date": day})
        if shares and priced_by is None:
            reason = reason or UNPRICED_CLASS
        elif shares and not close:
            reason = reason or NO_CLOSE
    out["shares"] = sum(c["shares"] * c["multiple"] for c in out["classes"])
    if reason:
        return {**out, "held_reason": reason}
    priced = [c for c in out["classes"] if c["shares"]]
    if not priced:
        return {**out, "held_reason": NO_COVER}
    return {**out, "value": sum(c["shares"] * c["multiple"] * c["close"] for c in priced), "close_date": min(c["close_date"] for c in priced)}
