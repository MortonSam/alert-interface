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

RISK_FACTORS_VERSION = 3              # 2 (2026-10-19): table-row item headings, bold lead-ins, title-case headings
                                      # 3 (same day): the opening of Item 1, Business (business)
BUSINESS_CHARS = 1500              # of Item 1's opening kept as evidence for the line on what the company does
RISK_HEADING_CHARS = (40, 600)
BODY_CHARS = 1500                  # of each risk's text kept for the model and the verifier
MIN_SECTION_CHARS = 2000           # a shorter "Item 1A" span is the table of contents or a cross-reference
MIN_HEADINGS = 3
PAGE_FURNITURE = re.compile(r"\d{1,3}|table of contents|page \d{1,3}", re.I)   # page numbers and running heads between paragraphs
HEADING_MAX_CHARS = 80            # an item heading ("Item 1A. Risk Factors") is short
BOILERPLATE = re.compile(r"forward-looking statements|should be read in conjunction|cautionary|the following risk|risk factors set forth|risk factors (?:below|described)|above summary|this (?:annual )?report on form", re.I)

_ITEM_1A = re.compile(r"\s*item\s*1a\s*[.:\-–—]?\s*(?:\n\s*)?risk\s+factors", re.I)
_ITEM_END = re.compile(r"\s*item\s*1b\s*[.:\-–—]?\s*(?:\n\s*)?unresolved|item\s*1c\s*[.:\-–—]?\s*(?:\n\s*)?cybersecurity|item\s*2\s*[.:\-–—]?\s*(?:\n\s*)?properties", re.I)
_ITEM_1 = re.compile(r"\s*item\s*1\s*[.:\-–—]?\s*(?:\n\s*)?business\b", re.I)
_BOLD = re.compile(r"font-weight\s*:\s*(?:bold|bolder|[6-9]00)", re.I)
_ITALIC = re.compile(r"font-style\s*:\s*italic", re.I)


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
    for el in root.iter("p", "div", "li", "tr"):
        if el.tag != "tr":
            if any(a.tag == "tr" for a in el.iterancestors()) or any(c.tag in ("p", "div", "li", "table") for c in el.iterdescendants()):
                continue
        text = " ".join(el.text_content().split())
        if not text:
            continue
        runs = _runs(el)
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
        if node.tag in ("b", "strong", "i", "em"):
            return True
        style = node.get("style") or ""
        if _BOLD.search(style) or _ITALIC.search(style):
            return True
        if node is stop:
            return False
        node = node.getparent()
    return False


def _runs(el) -> list[tuple[str, bool]]:
    """Every non-blank text run in document order, with whether it is emphasised (lxml keeps text on an element and the tail of
    each child, the tail belonging to the child's parent)."""
    runs: list[tuple[str, bool]] = []
    def walk(node):
        if (node.text or "").strip():
            runs.append((node.text, _emphasised(node, el)))
        for child in node:
            if isinstance(child.tag, str):
                walk(child)
            if (child.tail or "").strip():
                runs.append((child.tail, _emphasised(node, el)))
    walk(el)
    return runs


def item_1a(paragraphs: list[dict]) -> list[dict]:
    """Pure: the paragraphs of Item 1A: the longest span from a heading that names it to the next Item 1B, 1C or 2 heading."""
    best: tuple[int, int, int] | None = None
    for i, p in enumerate(paragraphs):
        if len(p["text"]) > HEADING_MAX_CHARS or not _ITEM_1A.match(p["text"]):
            continue                                   # a heading, never a sentence that refers to Item 1A
        j = i + 1
        while j < len(paragraphs) and not (len(paragraphs[j]["text"]) <= HEADING_MAX_CHARS and _ITEM_END.match(paragraphs[j]["text"])):
            j += 1
        size = sum(len(q["text"]) for q in paragraphs[i + 1:j])
        if best is None or size > best[0]:
            best = (size, i + 1, j)
    if not best or best[0] < MIN_SECTION_CHARS:
        return []
    return paragraphs[best[1]:best[2]]


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


CATEGORY = re.compile(r"^(?:general\s+)?risks?\s+(?:related|relating|associated|pertaining|regarding|concerning)\b|\brisks?$|risk factors?$|^summary\b", re.I)


def heading_text(t: str) -> bool:
    """A risk's heading: sentence length, not a category title ("Risks Related to Our Business", all capitals) or boilerplate."""
    t = t.strip()
    return (RISK_HEADING_CHARS[0] <= len(t) <= RISK_HEADING_CHARS[1] and not BOILERPLATE.search(t) and not CATEGORY.search(t.rstrip(". "))
            and t != t.upper() and t[:1].isupper())


def is_heading(p: dict) -> bool:
    return p["emphasis"] and heading_text(p["text"])


def risks(section: list[dict]) -> list[dict]:
    """Pure: [{n, heading, body}] in filing order: each emphasised sentence-length heading and the text after it."""
    out: list[dict] = []
    for p in section:
        if is_heading(p):
            out.append({"n": len(out) + 1, "heading": p["text"], "body": ""})
        elif p.get("lead") and heading_text(p["lead"]):
            out.append({"n": len(out) + 1, "heading": p["lead"], "body": p["text"][len(p["lead"]):].strip()[:BODY_CHARS]})
        elif out and len(out[-1]["body"]) < BODY_CHARS and not p["emphasis"] and not PAGE_FURNITURE.fullmatch(p["text"].strip()):
            out[-1]["body"] = (out[-1]["body"] + " " + p["text"]).strip()[:BODY_CHARS]
    return [r for r in out if r["body"]]


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
