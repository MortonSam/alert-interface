"""The risks a company names in Item 1A of its latest 10-K (Ivy's walkthrough, step 7).

Item 1A is found as the longest span from an "Item 1A ... Risk Factors" heading to the next "Item 1B" or "Item 2" heading (the
table of contents holds a short one). Inside it, each risk factor's heading is a paragraph set in bold or italic (or a paragraph's
bold lead-in) of sentence length (RISK_HEADING_CHARS); the paragraphs after it, up to the next heading, are its text. Category
titles ("Risks Related to Our Business", all capitals) are skipped. The model later chooses up to three headings and says
each in one plain sentence; the verifier checks that sentence against the heading and its text (services/walkthrough_story).

The same read keeps the opening of Item 1, Business (the longest span from an "Item 1 ... Business" heading to Item 1A, its first
BUSINESS_CHARS of plain paragraphs): the evidence for the walkthrough's plain line on what the company does, which a vendor's
description alone may not give (Realty Income's is a slogan).
"""
from __future__ import annotations

import re

RISK_FACTORS_VERSION = 4              # 2 (2026-10-19): table-row item headings, bold lead-ins, title-case headings
                                      # 3 (same day): the opening of Item 1, Business (business)
                                      # 4 (2026-11-10): underlined headings; "ITEM 1A | Risk Factors", "Part I - Item 1A.", "Item 1A" and
                                      #   "Risk Factors" in two paragraphs; a lone "Risk Factors" heading (a 10-K in annual-report form with a
                                      #   cross-reference index); the annual report exhibit (Exhibit 13) a bank's 10-K points Item 1A to
BUSINESS_CHARS = 1500              # of Item 1's opening kept as evidence for the line on what the company does
RISK_HEADING_CHARS = (40, 600)
BODY_CHARS = 1500                  # of each risk's text kept for the model and the verifier
MIN_SECTION_CHARS = 2000           # a shorter "Item 1A" span is the table of contents or a cross-reference
MIN_HEADINGS = 3
CAPS_HEADING_WORDS = 8             # a heading set in capitals (BRO, ISRG) is a risk when it runs a sentence; a short one is a category
PAGE_FURNITURE = re.compile(r"\d{1,3}|table of contents|page \d{1,3}", re.I)   # page numbers and running heads between paragraphs
HEADING_MAX_CHARS = 80            # an item heading ("Item 1A. Risk Factors") is short
BOILERPLATE = re.compile(r"forward-looking statements|should be read in conjunction|cautionary|the following risk|risk factors set forth|risk factors (?:below|described)|above summary|this (?:annual )?report on form", re.I)

_SEP = r"[\s.:,|\-–—]*"
_PART = r"\s*(?:part\s+i\b" + _SEP + r")?"
_1A = r"item\s*1\s*(?:\.\s*)?(?:a|\(a\))"                                     # "Item 1A", "Item 1.A." (CLX), "Item 1(a)" (HAL, ICE)
_ITEM_1A = re.compile(_PART + _1A + _SEP + r"risk\s+factors", re.I)
_ITEM_1A_ALONE = re.compile(_PART + _1A + _SEP + r"$", re.I)        # "Item 1A." with "Risk Factors" in the next paragraph
_RISK_FACTORS_ALONE = re.compile(r"\s*risk\s+factors\W*$", re.I)
# the next item's heading: "Item 1B. Unresolved Staff Comments", "Item 1C" or "Item 2", in any of the forms above, its title in the
# same paragraph or the next (VMC sets "ITEM 1B" alone)
_ITEM_END = re.compile(_PART + r"item\s*(?:1\s*(?:\.\s*)?(?:[bc]|\([bc]\))|2)(?![\d.]\d)" + _SEP + r"(?:unresolved|cybersecurity|properties|$)", re.I)
# the section after Item 1A in a 10-K without item headings in its body (annual-report form) or in an annual report exhibit
_NEXT_SECTION = re.compile(r"\s*(?:unresolved\s+staff\s+comments|cybersecurity|properties|legal\s+proceedings|management.s\s+discussion|"
                           r"quantitative\s+and\s+qualitative|selected\s+financial|market\s+for\s+(?:the\s+)?registrant|financial\s+statements|"
                           r"executive\s+officers|supervision\s+and\s+regulation|explanation\s+of\s+gaap|non-gaap|report\s+of\s+independent|recent\s+accounting)\b", re.I)
# a whole short heading that opens an annual report's next part (Citi's "MANAGING GLOBAL RISK", BNY's "Risk Management")
_NEXT_TITLE = re.compile(r"\s*(?:managing\s+global\s+risk|risk\s+management|overview|glossary|business\s+segments?|supplemental\s+information|"
                         r"consolidated\s+financial\s+statements|capital|liquidity\s+and\s+(?:capital|funding)|recent\s+accounting)\W*", re.I)
_TRAILING_PARENS = re.compile(r"\s*\([^)]*\)\s*$")
_ITEM_1 = re.compile(r"\s*item\s*1\s*[.:\-–—]?\s*(?:\n\s*)?business\b", re.I)
_BOLD = re.compile(r"font-weight\s*:\s*(?:bold|bolder|[6-9]00)", re.I)
_ITALIC = re.compile(r"font-style\s*:\s*italic", re.I)
_UNDERLINE = re.compile(r"text-decoration\s*:\s*underline", re.I)            # TXN's risk headings are underlined


HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")          # ZBH sets "Item 1A. Risk Factors" in an h2
BLOCK_TAGS = ("p", "div", "li", "table", *HEADING_TAGS)


def blocks(html: str | bytes) -> list[dict]:
    """Pure: the document's leaf paragraphs in order, {text, emphasis, lead}: emphasis is True when every visible character of the
    paragraph sits inside bold or italic markup (a b/strong/i/em tag or a font-weight/font-style style); lead is the paragraph's
    opening emphasised run when only its start is emphasised (a heading set inline before its text). A table row is one
    paragraph (filings set item headings in tables: AMZN's "Item 1A." and "Risk Factors" sit in two cells of one row)."""
    import lxml.html
    root = lxml.html.fromstring(html if isinstance(html, bytes) else html.encode("utf-8", "replace"))
    for bad in root.xpath("//script|//style"):
        bad.drop_tree()
    out: list[dict] = []
    for el in root.iter("p", "div", "li", "tr", *HEADING_TAGS):
        lead_only = False
        if el.tag != "tr":
            if any(a.tag == "tr" for a in el.iterancestors()):
                continue
            if any(c.tag in BLOCK_TAGS for c in el.iterdescendants()):
                lead_only = True                       # only its own text before its first block (ABBV's heading, then a rule set as a table)
        runs = _runs(el, lead_only)
        text = " ".join((_lead_text(el) if lead_only else el.text_content()).split())
        if not text:
            continue
        runs = [r for r in runs if not MARKER_RUN.fullmatch(r[0])]     # a bullet set apart from its bold heading (NOC) is not text
        lead_parts = []
        for t, emph in runs:
            if not emph:
                break
            lead_parts.append(t)
        lead = " ".join(" ".join(lead_parts).split())
        full = bool(runs) and all(e for _, e in runs)
        out.append({"text": text, "emphasis": full, "lead": None if full or not lead else lead})
    return out


def _emphasised(node, stop) -> bool:
    while node is not None:
        if node.tag in ("b", "strong", "i", "em", "u"):
            return True
        style = node.get("style") or ""
        if _BOLD.search(style) or _ITALIC.search(style) or _UNDERLINE.search(style):
            return True
        if node is stop:
            return False
        node = node.getparent()
    return False


def _lead_text(el) -> str:
    """The element's own text, spaces included, up to its first block child (a copy with that block and all after it cut off)."""
    import copy
    clone = copy.deepcopy(el)
    first = next((c for c in clone.iterdescendants() if isinstance(c.tag, str) and c.tag in BLOCK_TAGS), None)
    node = first
    while node is not None and node is not clone:
        parent = node.getparent()
        for sib in list(node.itersiblings()):
            parent.remove(sib)
        if node is first:
            parent.remove(node)
        else:
            node.tail = None
        node = parent
    return clone.text_content()


def _runs(el, lead_only: bool = False) -> list[tuple[str, bool]]:
    """Every non-blank text run in document order, with whether it is emphasised (lxml keeps text on an element and the tail of
    each child, the tail belonging to the child's parent). lead_only stops at the element's first block child."""
    runs: list[tuple[str, bool]] = []
    class Stop(Exception):
        pass
    def walk(node):
        if (node.text or "").strip():
            runs.append((node.text, _emphasised(node, el)))
        for child in node:
            if isinstance(child.tag, str):
                if lead_only and child.tag in BLOCK_TAGS:
                    raise Stop
                walk(child)
            if (child.tail or "").strip():
                runs.append((child.tail, _emphasised(node, el)))
    try:
        walk(el)
    except Stop:
        pass
    return runs


def _short(t: str) -> bool:
    return len(_TRAILING_PARENS.sub("", t)) <= HEADING_MAX_CHARS     # NEM's heading runs on into "(dollars in millions, ...)"


def _starts_1a(paragraphs: list[dict], i: int) -> bool:
    t = paragraphs[i]["text"]
    if _short(t) and _ITEM_1A.match(t):
        return True
    return bool(_ITEM_1A_ALONE.match(t) and i + 1 < len(paragraphs) and _RISK_FACTORS_ALONE.match(paragraphs[i + 1]["text"]))


def _longest(paragraphs: list[dict], starts, ends, first: bool = False) -> list[dict]:
    """Pure: the longest span from a start to the next end (first=True: the first span long enough to be a section)."""
    best: tuple[int, int, int] | None = None
    for i in range(len(paragraphs)):
        if not starts(i):
            continue
        j = i + 1
        while j < len(paragraphs) and not ends(j):
            j += 1
        size = sum(len(q["text"]) for q in paragraphs[i + 1:j])
        if first and size >= MIN_SECTION_CHARS:
            return paragraphs[i + 1:j]
        if best is None or size > best[0]:
            best = (size, i + 1, j)
    if not best or best[0] < MIN_SECTION_CHARS:
        return []
    return paragraphs[best[1]:best[2]]


def item_1a(paragraphs: list[dict]) -> list[dict]:
    """Pure: the paragraphs of Item 1A: the longest span from a heading that names it to the next Item 1B, 1C or 2 heading. Without
    one, the longest span from a lone emphasised "Risk Factors" heading to the next section's heading (_NEXT_SECTION or an item)."""
    short_end = lambda j: _short(paragraphs[j]["text"]) and bool(_ITEM_END.match(paragraphs[j]["text"]))
    found = _longest(paragraphs, lambda i: _starts_1a(paragraphs, i), short_end)
    if found:
        return found
    return _longest(paragraphs, lambda i: paragraphs[i]["emphasis"] and bool(_RISK_FACTORS_ALONE.match(paragraphs[i]["text"])),
                    lambda j: short_end(j) or (paragraphs[j]["emphasis"] and _short(paragraphs[j]["text"]) and bool(
                        _NEXT_SECTION.match(paragraphs[j]["text"]) or _NEXT_TITLE.fullmatch(paragraphs[j]["text"])))
                    or _starts_1a(paragraphs, j), first=True)      # a later lone "Risk Factors" names a note or a table, never the section


def item_1(paragraphs: list[dict], chars: int = BUSINESS_CHARS) -> str:
    """Pure: the opening of Item 1, Business: the longest span from its heading to the Item 1A heading, its first `chars` of
    plain paragraphs (headings, page furniture and boilerplate left out); "" when not found. The research note's verifier reads
    more of it (note_business.EVIDENCE_CHARS)."""
    best: tuple[int, int, int] | None = None
    for i, p in enumerate(paragraphs):
        if len(p["text"]) > HEADING_MAX_CHARS or not _ITEM_1.match(p["text"]):
            continue
        j = i + 1
        while j < len(paragraphs) and not (len(paragraphs[j]["text"]) <= HEADING_MAX_CHARS and _ITEM_1A.match(paragraphs[j]["text"])):
            j += 1
        size = sum(len(q["text"]) for q in paragraphs[i + 1:j])
        if best is None or size > best[0]:
            best = (size, i + 1, j)
    if not best or best[0] < MIN_SECTION_CHARS:
        return ""
    out = ""
    for q in paragraphs[best[1]:best[2]]:
        t = q["text"].strip()
        if q["emphasis"] or len(t) < HEADING_MAX_CHARS or PAGE_FURNITURE.fullmatch(t) or BOILERPLATE.search(t):
            continue
        out = (out + " " + t).strip()
        if len(out) >= chars:
            break
    return out[:chars]


MARKER_RUN = re.compile(r"[\s•■▪●◦·*\u200b]*")
# a list marker before a heading: "■The effects of..." (AOS), "•Increases in..." (DOV), "* The Company's..." (MMM), "a.Events..." (CCL)
MARKER = re.compile(r"^(?:[\s•■▪●◦·*]+|[a-z]\.\s*(?=[A-Z])|\([a-z0-9]{1,3}\)\s*)")


def unmarked(t: str) -> str:
    """Pure: a heading without its list marker."""
    return MARKER.sub("", t.strip(), count=1).strip()


CATEGORY = re.compile(r"^(?:general\s+)?risks?\s+(?:related|relating|associated|pertaining|regarding|concerning)\b|\brisks?$|risk factors?$|^summary\b", re.I)


# a page's running head (RJF's "RAYMOND JAMES FINANCIAL, INC. AND SUBSIDIARIES Index", SO's "Table of Contents Index to Financial
# Statements"), another item's name, or the safe-harbor title, set in the same type as a heading
NOT_A_HEADING = re.compile(r"table of contents|index to (?:consolidated )?financial statements|(?:\b|subsidiaries)index$|^item\s*\d|litigation\s+reform\s+act|safe\W+harbor", re.I)


def heading_text(t: str, lead: bool = False) -> bool:
    """A risk's heading: sentence length, not a category title ("Risks Related to Our Business", all capitals) or boilerplate. A
    whole paragraph ending in a colon labels a group ("Copyright and other intellectual property:"); a lead-in may end in one (IBM)."""
    t = unmarked(t)
    return (RISK_HEADING_CHARS[0] <= len(t) <= RISK_HEADING_CHARS[1] and not BOILERPLATE.search(t) and not CATEGORY.search(t.rstrip(". "))
            and not NOT_A_HEADING.search(t) and (t != t.upper() or len(t.split()) >= CAPS_HEADING_WORDS) and t[:1].isupper()
            and (lead or not t.endswith(":")))


def is_heading(p: dict) -> bool:
    return p["emphasis"] and heading_text(p["text"])


def risks(section: list[dict]) -> list[dict]:
    """Pure: [{n, heading, body}] in filing order: each emphasised sentence-length heading and the text after it."""
    out: list[dict] = []
    for p in section:
        if is_heading(p):
            out.append({"n": len(out) + 1, "heading": unmarked(p["text"]), "body": ""})
        elif p.get("lead") and heading_text(p["lead"], lead=True):
            body = p["text"].split(p["lead"], 1)[-1] if p["lead"] in p["text"] else p["text"][len(p["lead"]):]
            out.append({"n": len(out) + 1, "heading": unmarked(p["lead"]), "body": body.strip()[:BODY_CHARS]})
        elif (out and len(out[-1]["body"]) < BODY_CHARS and not p["emphasis"] and not PAGE_FURNITURE.fullmatch(p["text"].strip())
              and not MARKER_RUN.fullmatch(p["text"])):
            out[-1]["body"] = (out[-1]["body"] + " " + p["text"]).strip()[:BODY_CHARS]
    # a heading met twice (WTW's summary lists every heading before the full text) is the occurrence with its text, numbered in order
    kept = {}
    for r in out:
        if r["body"] and (r["heading"] not in kept or len(r["body"]) > len(kept[r["heading"]]["body"])):
            kept[r["heading"]] = r
    final = sorted(kept.values(), key=lambda r: r["n"])
    return [{**r, "n": i + 1} for i, r in enumerate(final)]


def read_html(html: str | bytes) -> dict:
    """Pure: {ok, risks, section_chars, business} or {ok: False, reason, business}."""
    paragraphs = blocks(html)
    business = item_1(paragraphs)
    section = item_1a(paragraphs)
    if not section:
        return {"ok": False, "reason": "Item 1A could not be found in the 10-K", "business": business}
    found = risks(section)
    if len(found) < MIN_HEADINGS:
        return {"ok": False, "reason": f"Item 1A's risk headings could not be read ({len(found)} found)", "section_chars": sum(len(p["text"]) for p in section),
                "business": business}
    return {"ok": True, "risks": found, "section_chars": sum(len(p["text"]) for p in section), "business": business}


# where a bank's 10-K keeps its annual report: an Exhibit 13, or the filing's other main document ("usb-20251231_d2.htm" beside
# "usb-20251231.htm")
EXHIBIT_13 = re.compile(r"ex-?13|exhibit-?13|ex13|-\d{8}(?:_d\d+)?\.htm$", re.I)


async def read_risk_factors(edgar, ciks: list[str]) -> dict:
    """The latest 10-K's risk factors (read_html) with the filing's receipt {accession, filed, form, url}. A 10-K whose Item 1A only
    points to its annual report (USB: "Information in response to this Item 1A can be found in the 2025 Annual Report") is read
    from that exhibit, and the receipt names it."""
    from app.services.segments import latest_annual_for
    cik, k = await latest_annual_for(edgar, ciks)
    if not k:
        return {"ok": False, "reason": "no 10-K on file at the SEC"}
    html = await edgar.fetch_filing_html(cik, k["accession"], k["primary_document"])
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{k['accession'].replace('-', '')}/"
    got = read_html(html)
    url = base + k["primary_document"]
    if not got["ok"]:
        names = await edgar.list_filing_documents(cik, k["accession"], every_exhibit=True)
        for name in [n for n in names if EXHIBIT_13.search(n) and n != k["primary_document"]]:
            ex = read_html(await edgar.fetch_filing_document(cik, k["accession"], name))
            if ex["ok"]:
                got, url = {**ex, "business": got.get("business") or ex.get("business")}, base + name
                break
    return {**got, "accession": k["accession"], "filed": k["filed"], "form": k["form"], "url": url}
