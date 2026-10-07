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
SHARE_EXCHANGE = re.compile(r"exchange ratio|stock-for-stock|in exchange for shares|shares of (?:the )?(?:company'?s? )?common stock(?: of the company)? (?:were|was) issued|"
                            r"converted into the right to receive (?:[\d.]+ )?(?:shares? of|of a share)|all-stock", re.I)
# the filer's own shares converted into cash: the filer was bought for cash and will stop trading (never a share exchange)
CASH_TARGET = re.compile(r"each share of (?:(?:the )?(?:company'?s?|registrant'?s?|[A-Z][\w&.'’]*'?s?) )?(?:series [a-z] )?common stock.{0,900}?converted into the right to receive (?:an amount in )?cash", re.I | re.S)
# a defined term for a company: 'Becton, Dickinson and Company, a New Jersey corporation ("BD")'
_DEFINITION = re.compile(r"([A-Z][\w&.,'’ ]{2,80}?),? an? [A-Z][a-z]+(?: [A-Z][a-z]+)? (?:corporation|company|limited liability company|limited partnership)[^(]{0,40}\(\W{0,3}([A-Z][\w&.]{1,30})\W{0,3}\)")


def resolve_defined(term: str, text: str) -> str:
    """Pure: the full name a filing gave a defined term ("BD" -> "Becton, Dickinson and Company"), else the term itself."""
    for m in _DEFINITION.finditer(text):
        if m.group(2).strip().lower() == term.strip().lower():
            return m.group(1).strip(" ,")
    return term
# a Reverse Morris Trust: another company spun a business to its own holders, which then merged into the filer for the filer's shares: the filer acquired
RMT = re.compile(r"spin-?off of (?P<spinner>[A-Z][\w&.,'’ ]{1,60}?)(?:'s|’s) (?P<business>[A-Z][\w&.,'’ ]{2,80}? business)[^.]{0,120}?(?:combination|merger) of (?:the )?[^.]{0,80}? with (?P<filer>[A-Z][\w&.,'’ ]{1,50}?)\b", re.I)
RMT_DISTRIBUTION = re.compile(r"distributed,? on a pro rata basis[^.]{0,200}? to (?:each )?holders? of (?P<spinner>[A-Z][\w&.'’]+(?: [A-Z][\w&.'’]+){0,3}) common stock", re.I)
ACQUIRE = re.compile(r"completed (?:its |the )?(?:previously announced )?acquisition of|acquired (?:all of )?(?:the )?(?:issued and )?outstanding|acquisition of all", re.I)
# the counterparty: the capitalised name after the verb
_NAME_AFTER = re.compile(r"(?:spin-?off of|separation of|distribution of|acquisition of|acquired|merger (?:with|of)|merged with(?: and into)?|combination with|business combination with)\s+"
                         r"(?:all of )?(?:the )?(?:issued and outstanding )?(?:shares of |common stock of |equity interests of |capital stock of )?(?:its |the )?"
                         r"((?:[A-Z][A-Za-z0-9&.,'’-]*\s?){1,7}(?:Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.|LLC|L\.P\.|LP|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|Holdings|Group|Freight|Business|Technologies|Systems|Services|Partners))", re.S)   # greedy: "Gamma Holdings, Inc." whole
_NAME_LOOSE = re.compile(r"(?:spin-?off of|separation of|acquisition of|acquired|merger with|merged with|combination with)\s+(?:its |the )?((?:[A-Z][A-Za-z0-9&'’-]+\s?){1,5})")


# the completion date the filing itself names: "Effective August 19, 2026 (the “Closing Date”)", "closing on August 17, 2026 (the “Closing Date”)",
# "on June 29, 2026, the Company completed the Spin-Off"; an agreement date or the cover's event date is never taken over these
_CLOSING_DATE = re.compile(rf"(?:on|effective(?: as of)?)\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})\s*\((?:the\s*)?[“\"]?\s*(?:Closing Date|Distribution Date|Effective Date)", re.I)
_COMPLETED_ON = re.compile(rf"(?:on|as of)\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}}),?\s+(?:the Company|[A-Z][\w.&'’]*(?: [A-Z][\w.&'’]*){{0,4}})\s+completed the (?:previously announced )?(?:Spin-Off|Distribution|Separation|Merger|Combination|Transactions?)", re.I)
# the counterparties a combination names: "transaction with Liberty Broadband Corporation, a Delaware corporation", "transaction with Cox Enterprises, Inc."
_WITH = re.compile(r"(?:transactions?|combination|merger|business combination)\s+with\s+((?:[A-Z][\w&.'’-]*)(?:[ ,]+(?:[A-Z][\w&.'’-]*|and))*?(?:,? (?:Inc\.?|Corp\.?|Corporation|Company|LLC|L\.P\.|plc|Ltd\.?))?)(?=,? an? [A-Z][a-z]+(?: [A-Z][a-z]+)* (?:corporation|company|limited|real estate)|\s*\(|,|\.| pursuant)")
# the company spun off, from the distribution sentence: "shares of common stock of Honeywell Aerospace, par value $0.01"
_SPUN_COMPANY = re.compile(r"shares of (?:common stock|capital stock|common shares) of ([A-Z][\w&.'’-]*(?: [A-Z][\w&.'’-]*){0,5}?)(?:,? par value|\s*\(|,|\s+(?:to|on|was|were)\b)")
_SHARE_CLASS = re.compile(r"\b(?:Class|Series)\s+[A-Z]\b|\b(?:Common|Preferred)(?:\s+Stock)?$|^(?:Company|Registrant|Charter|Parent)$", re.I)
_STRUCTURAL_TERM = re.compile(r"Merger Sub|Merger LLC|Parent|NewCo|SpinCo|Holdings|Operating Partnership|^Sub$|^Company$|^Registrant$", re.I)
_CORP_SUFFIX = re.compile(r",?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.|LLC|L\.P\.|LP|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.)$")


def completion_date(flat: str) -> date | None:
    """Pure: the date the filing names as the completion, when it names one (the first 15,000 characters: the cover, the
    introductory note and the items)."""
    m = _COMPLETED_ON.search(flat[:15000]) or _CLOSING_DATE.search(flat[:15000])
    return _to_date(m) if m else None


def counterparties(flat: str, issuer: str | None) -> list[str]:
    """Pure: the companies a combination names as its other parties ("transaction with X"), in filing order, without the
    issuer, its subsidiaries or structural defined terms; a parent whose operating company the filing also defines by the
    same first word carries it in parentheses ("Cox Enterprises, Inc. (Cox Communications, LLC)")."""
    own = {f.lower() for f in (issuer_forms(issuer) if issuer else [])}
    out: list[str] = []
    for m in _WITH.finditer(flat[:8000]):
        name = _clean_name(m.group(1))
        low = name.lower()
        if not name or _SHARE_CLASS.search(name) or _STRUCTURAL_TERM.search(name) or low in own or any(low.startswith(f + " ") or f.startswith(low + " ") for f in own):
            continue
        tail = flat[m.end():m.end() + 140]
        if re.search(r"subsidiary of", tail.split("(")[0], re.I):      # "X, a Delaware corporation and wholly owned subsidiary of Y (“Term”)": a party's subsidiary, not a party
            continue
        if name not in out:
            out.append(name)
    for i, name in enumerate(out):
        first = name.split()[0]
        for d in re.finditer(rf"({re.escape(first)} [A-Z][\w&.'’-]*(?:, (?:LLC|Inc\.?))?)(?: \(f/k/a [^)]*\))?\s*\(\W{{0,3}}{re.escape(first)}\W{{0,3}}\)", flat[:12000]):
            other = _clean_name(d.group(1))
            if other != name and not _STRUCTURAL_TERM.search(other):
                out[i] = f"{name} ({other})"
                break
    return out


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
    """Pure: None for a defined term, a bare suffix or a share-class label ("Company Class B", "Series A", "Charter Class A Common");
    otherwise the name."""
    if not name or _SUFFIX_ONLY.match(name) or _DEFINED_TERM.match(name) or _SHARE_CLASS.search(name):
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
    rmt = RMT.search(head) or RMT.search(flat[:8000])
    own_forms = {f.lower() for f in (issuer_forms(issuer) if issuer else [])}
    spinner_is_other = bool(rmt) and rmt.group("spinner").strip().lower() not in own_forms and not any(rmt.group("spinner").strip().lower().startswith(f) for f in own_forms)
    if rmt and spinner_is_other and SHARE_EXCHANGE.search(flat):
        # another company's holders received the business and then the filer's shares: the filer is the acquirer, by share exchange
        spinner = resolve_defined(rmt.group("spinner").strip(), flat[:8000])
        name = f"{spinner} ({rmt.group('business').strip().removesuffix(' business').removesuffix(' Business')})"
        dm = _DATE.search(head)
        return {"kind": "acquisition", "date": completion_date(flat) or (_to_date(dm) if dm else filed), "name": name, "evidence": head[:300], "spinner": spinner, "spinner_kind": "spin_off"}
    if CASH_TARGET.search(passage) or CASH_TARGET.search(flat[:20000]):
        kind = "other"          # the target's shares became cash: a cash deal on either side; the delisting rule, not the P/E rule, handles a filer that stops trading
    elif SPIN.search(head):
        kind = "spin_off"
    elif MERGER.search(head) and (SHARE_EXCHANGE.search(flat) or re.search(r"merger of equals|merged with and into", head, re.I)):
        kind = "merger"
    elif ACQUIRE.search(head) and SHARE_EXCHANGE.search(flat):
        kind = "acquisition"
    else:
        kind = "other"          # a cash acquisition, an asset sale, or an unread form of consideration
    dm = _DATE.search(head)
    day = completion_date(flat) or (_to_date(dm) if dm else filed)
    nm = _NAME_AFTER.search(head)
    name = _clean_name(nm.group(1)) if nm else None
    if name and (re.match(r"^(?:The |Its |All |Each )", name) or _SUFFIX_ONLY.match(name) or _SHARE_CLASS.search(name) or (issuer and name.lower() in {f.lower() for f in issuer_forms(issuer)})):
        name = None
    name = _usable_name(name)                             # a defined term ("Merger LLC") or a share-class label is no name, so the rules below may fill it
    if kind == "spin_off":
        sc = _SPUN_COMPANY.search(flat[:15000])
        spun = _clean_name(sc.group(1)) if sc else None
        if spun and _usable_name(spun) and not (issuer and spun.lower() in {f.lower() for f in issuer_forms(issuer)}):
            name = spun                                   # the company distributed, named in the distribution sentence (Honeywell Aerospace)
    if kind in ("merger", "acquisition"):
        parties = counterparties(flat, issuer)
        if len(parties) > 1 or (parties and not name):
            name = " and ".join(parties)                  # every party the combination names (Liberty Broadband and Cox)
    if not name:
        name = _name_from_common_stock(head, issuer) or _name_from_common_stock(flat, issuer)
    if not name:
        lm = _NAME_LOOSE.search(head)
        cand = _clean_name(lm.group(1)) if lm else None
        if cand and cand.lower() not in {"its", "the", "all", "each"} and not _SUFFIX_ONLY.match(cand) and not (issuer and cand.lower() in {f.lower() for f in issuer_forms(issuer)}):
            name = cand
    name = _usable_name(name)
    if name and " " not in name and " and " not in name:
        name = resolve_defined(name, flat[:12000])       # a defined term stands for its company ("AvalonBay" -> "AvalonBay Communities, Inc.")
    return {"kind": kind, "date": day, "name": _usable_name(name), "evidence": head[:300]}
