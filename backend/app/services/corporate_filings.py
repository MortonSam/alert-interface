"""Corporate actions read from filings: an 8-K with Item 2.01 (completion of acquisition or disposition of assets) says what the
company completed and with whom. classify_item_201 reads the filing's text and returns the kind (spin_off, merger, acquisition
by share exchange, or other), the completion date and the counterparty's name, each from the words of the filing itself.
Nothing is inferred beyond the text; a filing the rules cannot read is reported as unclassified."""
from __future__ import annotations

import re
from datetime import date

from app.services.report_announcements import issuer_forms

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
_ITEM_201 = re.compile(r"Item\s+2\.01\.?\s*(?:Completion of (?:the )?Acquisition or Disposition of Assets\.?)?", re.I)
_NEXT_ITEM = re.compile(r"Item\s+(?:[13-9]|2\.0[2-9])\.", re.I)
SPIN = re.compile(r"spin-?off|separation of|separated|spun off|pro rata distribution|distribution of (?:all|100%|\d{2}(?:\.\d)?%) of the (?:outstanding )?(?:shares|common stock)|distributed (?:all|100%)"
                  r"|\bthe (?:Distribution|Separation|Spin-Off)\b|effected the distribution|completed the separation", re.I)
_COMMON_STOCK_NAME = re.compile(r"((?:[A-Z][A-Za-z0-9&.'’-]*\s){1,4}?)(?:Common Stock|common stock)\b")
_REFERENCE_ONLY = re.compile(r"incorporated (?:herein )?by reference", re.I)
MERGER = re.compile(r"merger of equals|merged with and into|merger agreement|combination with|business combination|merged with", re.I)
SHARE_EXCHANGE = re.compile(r"exchange ratio|stock-for-stock|in exchange for shares|shares of (?:the )?(?:company'?s? )?common stock(?: of the company)? (?:were|was) issued|each share of .{0,80}? (?:was|were) converted into (?:the right to receive )?\d|all-stock", re.I)
ACQUIRE = re.compile(r"completed (?:its |the )?(?:previously announced )?acquisition of|acquired (?:all of )?(?:the )?(?:issued and )?outstanding|acquisition of all", re.I)
# the counterparty: the capitalised name after the verb
_NAME_AFTER = re.compile(r"(?:spin-?off of|separation of|distribution of|acquisition of|acquired|merger (?:with|of)|merged with(?: and into)?|combination with|business combination with)\s+"
                         r"(?:all of )?(?:the )?(?:issued and outstanding )?(?:shares of |common stock of |equity interests of |capital stock of )?(?:its |the )?"
                         r"((?:[A-Z][A-Za-z0-9&.,'’-]*\s?){1,7}(?:Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.|LLC|L\.P\.|LP|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|Holdings|Group|Freight|Business|Technologies|Systems|Services|Partners))", re.S)   # greedy: "Gamma Holdings, Inc." whole
_NAME_LOOSE = re.compile(r"(?:spin-?off of|separation of|acquisition of|acquired|merger with|merged with|combination with)\s+(?:its |the )?((?:[A-Z][A-Za-z0-9&'’-]+\s?){1,5})")


def _to_date(m: re.Match) -> date | None:
    try:
        return date(int(m.group(3)), [x.lower() for x in _MONTHS.split("|")].index(m.group(1).lower()) + 1, int(m.group(2)))
    except ValueError:
        return None


def item_201_text(text: str) -> str | None:
    """Pure: the Item 2.01 passage of an 8-K's text (through the next item heading), or None when the filing has no such item."""
    flat = re.sub(r"\s+", " ", text or "")
    m = _ITEM_201.search(flat)
    if not m:
        return None
    rest = flat[m.end():]
    n = _NEXT_ITEM.search(rest)
    return rest[: n.start()] if n else rest[:4000]


_SUFFIX_ONLY = re.compile(r"^(?:Inc\.?|Corp\.?|Co\.?|Ltd\.?|LLC|L\.P\.|plc|Company|Corporation|Incorporated|Holdings|Group)$", re.I)
# a filing's defined term, not a company's name: left unread so the reason says "a business" until someone records the name
_DEFINED_TERM = re.compile(r"^(?:SpinCo|RemainCo|New Company|NewCo|Merger Sub(?:sidiary)?|Merger LLC|Merger Corp\.?|Operating Partners(?:hip)?|Parent|Purchaser|Seller|Buyer|Acquisition Sub|"
                           r"Aerospace|the Business|Business|Issuer Solutions Business|Holdco|Sub|Target)$", re.I)


def _usable_name(name: str | None) -> str | None:
    """Pure: None for a defined term or a bare suffix; otherwise the name."""
    if not name or _SUFFIX_ONLY.match(name) or _DEFINED_TERM.match(name):
        return None
    return name


def _clean_name(raw: str) -> str:
    """Pure: a name as the filing writes it: the last sentence fragment only ("Separation. Qnity" -> "Qnity"), trailing commas
    gone, a trailing period kept only after a corporate suffix ("Inc.")."""
    name = re.sub(r"\s+", " ", raw).strip()
    name = name.split(". ")[-1].strip(" ,")
    if name.endswith(".") and not re.search(r"\b(?:Inc|Corp|Co|Ltd|L\.P|N\.V|S\.A)\.$", name):
        name = name.rstrip(".")
    return name


def _name_from_common_stock(text: str, issuer: str | None) -> str | None:
    """Pure: the first "<Name> Common Stock" that is not the issuer's own stock ("Qnity Common Stock", "FedEx Freight common stock")."""
    own = {f.lower() for f in (issuer_forms(issuer) if issuer else [])} | {"company", "the company", "registrant", "the registrant"}
    for m in _COMMON_STOCK_NAME.finditer(text):
        name = _clean_name(m.group(1))
        low = name.lower()
        if low in own or any(low == f or f.startswith(low + " ") for f in own) or low.startswith(("the ", "its ", "each ", "such ", "of ", "shares of ", "outstanding ")):
            continue
        if re.match(r"^(?:Class [A-Z]|Series [A-Z]|New|Old|Common|Preferred)$", name) or not _usable_name(name):
            continue
        return name
    return None


def classify_item_201(text: str, filed: date | None = None, issuer: str | None = None) -> dict | None:
    """Pure: {kind, date, name, evidence} from an 8-K's Item 2.01 passage; None when the filing has no Item 2.01. When the
    passage only incorporates another item by reference, the whole filing text is read. kind is spin_off, merger, acquisition
    (by share exchange), or other (a cash deal, an asset sale, anything unread). `issuer` (the company's own name) keeps its own
    stock from being read as the counterparty."""
    passage = item_201_text(text)
    if passage is None:
        return None
    flat = re.sub(r"\s+", " ", text)
    head = passage[:1500]
    if len(passage.strip()) < 120 or _REFERENCE_ONLY.search(passage[:300]):
        head = flat[:6000]
    if SPIN.search(head):
        kind = "spin_off"
    elif MERGER.search(head) and (SHARE_EXCHANGE.search(flat) or re.search(r"merger of equals|merged with and into", head, re.I)):
        kind = "merger"
    elif ACQUIRE.search(head) and SHARE_EXCHANGE.search(flat):
        kind = "acquisition"
    else:
        kind = "other"          # a cash acquisition, an asset sale, or an unread form of consideration
    dm = _DATE.search(head)
    day = _to_date(dm) if dm else filed
    nm = _NAME_AFTER.search(head)
    name = _clean_name(nm.group(1)) if nm else None
    if name and (re.match(r"^(?:The |Its |All |Each )", name) or _SUFFIX_ONLY.match(name) or (issuer and name.lower() in {f.lower() for f in issuer_forms(issuer)})):
        name = None
    if not name:
        name = _name_from_common_stock(head, issuer) or _name_from_common_stock(flat, issuer)
    if not name:
        lm = _NAME_LOOSE.search(head)
        cand = _clean_name(lm.group(1)) if lm else None
        if cand and cand.lower() not in {"its", "the", "all", "each"} and not _SUFFIX_ONLY.match(cand) and not (issuer and cand.lower() in {f.lower() for f in issuer_forms(issuer)}):
            name = cand
    return {"kind": kind, "date": day, "name": _usable_name(name), "evidence": head[:300]}
