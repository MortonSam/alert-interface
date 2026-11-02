"""Material 8-Ks: what makes a research note out of date between earnings reports (Sam, 2026-11-02).

A note is written again after each earnings report (note_currency, generate_notes) and after any material 8-K, found by the nightly
reader (scripts/scan_material_filings) in each company's SEC filing index:

  - always: Items 1.01 (a material agreement), 1.02 (one ended), 2.01 (an acquisition or disposition completed), 2.05 (exit or
    disposal costs), 2.06 (a material impairment), 5.01 (a change in control) and 5.02 (directors or officers)
  - Items 7.01 and 8.01 only when the filing's own text announces guidance, a deal or a major legal matter (kinds(): GUIDANCE, DEAL,
    LEGAL, from the cover and its exhibits)

Item 2.02 (results) is the earnings report itself and is covered by the report rule, and so is a 7.01 or 8.01 filed with it (an
earnings release's outlook). Each 8-K read is stored once, material or not,
under material_filings:{SYMBOL} with an excerpt of its own words; a note written after it reads that excerpt as a source (prompt_block),
the writer's and the checker's alike, so the new note can state what the filing says. pending_for() names a material filing newer than
the note, which tonight's run writes the note again for.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

ALWAYS = {"1.01", "1.02", "2.01", "2.05", "2.06", "5.01", "5.02"}
IF_ANNOUNCES = {"7.01", "8.01"}
RESULTS = "2.02"
KEY = "material_filings:{sym}"
KEEP_DAYS = 120                  # filings older than this leave the stored list
EXCERPT_CHARS = 4000             # one filing's words as the note's source
PROMPT_FILINGS = 2               # the newest material filings a note is written from

GUIDANCE = re.compile(r"\b(?:guidance|outlook)\b[^.]{0,80}\b(?:rais|lower|reaffirm|updat|introduc|withdr|narrow|expect)\w*"
                      r"|\b(?:rais|lower|reaffirm|updat|introduc|withdr|narrow)\w* (?:its |the )?(?:(?:full[- ]year|fiscal(?: year)?|20\d\d|annual|quarterly)\s+){0,3}(?:financial )?(?:guidance|outlook)", re.I)
DEAL = re.compile(r"definitive (?:merger |purchase |acquisition |sale |separation )?agreement|agreed to (?:acquire|be acquired|sell|merge|combine)"
                  r"|entered into an agreement to (?:acquire|sell|merge)|(?:proposed|pending) (?:acquisition|merger|sale|spin-?off|separation)"
                  r"|announce[sd]? (?:the |its |a )?(?:acquisition|merger|sale|spin-?off|separation|divestiture)", re.I)
LEGAL = re.compile(r"\b(?:settlement agreement|agreed to settle|class action|jury (?:verdict|returned)|verdict|indict(?:ed|ment)|consent decree"
                   r"|Department of Justice|Federal Trade Commission|(?:SEC|Securities and Exchange Commission) (?:investigation|charges|complaint)"
                   r"|subpoena|criminal (?:charges|investigation)|antitrust (?:lawsuit|suit|complaint))\b", re.I)


def items_of(record: dict) -> set[str]:
    """Pure: the 8-K's items, from EDGAR's comma-separated list ("2.02,9.01")."""
    return {i.strip() for i in (record.get("items") or "").split(",") if i.strip()}


def kinds(text: str) -> list[str]:
    """Pure: what a 7.01 or 8.01 filing announces, from its own words: guidance, deal, legal (empty: none of them)."""
    out = []
    if GUIDANCE.search(text):
        out.append("guidance")
    if DEAL.search(text):
        out.append("deal")
    if LEGAL.search(text):
        out.append("legal")
    return out


def needs_text(record: dict) -> bool:
    """Pure: the filing must be read to decide (7.01 or 8.01 with no always-material item)."""
    it = items_of(record)
    return bool(it & IF_ANNOUNCES) and not (it & ALWAYS) and RESULTS not in it


def verdict(record: dict, text: str | None) -> tuple[bool, list[str]]:
    """Pure: (material, why): the always-material items it holds, or what a 7.01/8.01 filing's text announces."""
    it = items_of(record)
    hard = sorted(it & ALWAYS)
    if hard:
        return True, [f"Item {i}" for i in hard]
    if RESULTS in it:
        return False, []                  # an earnings release (its 7.01 outlook too): the report rule writes the note again
    if it & IF_ANNOUNCES and text:
        k = kinds(text)
        return bool(k), k
    return False, []


_ITEM_START = re.compile(r"Item\s+\d\.\d\d", re.I)
_SIGNATURE = re.compile(r"\bSIGNATURES?\b")


def excerpt(texts: list[tuple[str, str]]) -> str:
    """Pure: the filing's own words for the note: the cover's items (from the first "Item" to the signatures) and then the first
    exhibit, whitespace collapsed, at most EXCERPT_CHARS."""
    parts = []
    for i, (_, t) in enumerate(texts[:2]):
        flat = re.sub(r"\s+", " ", t or "").strip()
        if i == 0:
            m = _ITEM_START.search(flat)
            flat = flat[m.start():] if m else flat
            s = _SIGNATURE.search(flat)
            flat = flat[:s.start()] if s else flat
        parts.append(flat)
    return " ".join(p for p in parts if p)[:EXCERPT_CHARS]


def filing_url(cik: str, accession: str, primary: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary}"


async def stored(db, symbol: str) -> list[dict]:
    from app.services.system_metadata_service import get_value
    raw = await get_value(db, KEY.format(sym=symbol))
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def _accepted(r: dict) -> datetime | None:
    a = r.get("acceptance") or ""
    try:
        return datetime.fromisoformat(a.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(f"{r['filed_on']}T23:59:59+00:00")
        except (KeyError, ValueError):
            return None


def newer_than(rows: list[dict], when: datetime | None) -> list[dict]:
    """Pure: the material filings accepted after `when` (all of them when None), newest first."""
    out = [r for r in rows if r.get("material") and (when is None or ((_accepted(r) or datetime.min.replace(tzinfo=timezone.utc)) > when))]
    return sorted(out, key=lambda r: r.get("acceptance") or r.get("filed_on") or "", reverse=True)


async def pending_for(db, symbol: str, written: datetime | None) -> dict | None:
    """The newest material filing accepted after the note was written, as the page names it, or None."""
    if written is None:
        return None
    rows = newer_than(await stored(db, symbol), written)
    if not rows:
        return None
    r = rows[0]
    return {"form": "8-K", "items": r.get("items"), "why": r.get("why"), "filed_on": r.get("filed_on"), "url": r.get("url")}


async def prompt_block(db, symbol: str, base_filing_date: str | None, before: datetime | None = None) -> str | None:
    """The material filings a note is written from (and checked against): those filed after the 10-Q or 10-K it rests on and, for a
    note already written (`before`), accepted before it was. None when there are none."""
    rows = [r for r in newer_than(await stored(db, symbol), None)
            if (not base_filing_date or (r.get("filed_on") or "") > str(base_filing_date)[:10])
            and (before is None or (_accepted(r) or before) <= before)][:PROMPT_FILINGS]
    if not rows:
        return None
    blocks = [f"--- 8-K filed {r['filed_on']} ({', '.join(r.get('why') or [])}) ---\n{r.get('excerpt') or '(text not read)'}" for r in rows]
    return ("MATERIAL FILINGS SINCE THAT REPORT (the company's own 8-K words; state what they say where it matters, and nothing beyond it):\n"
            + "\n".join(blocks) + "\n--- END MATERIAL FILINGS ---\n")


async def scan(db, edgar, symbol: str, today: date) -> dict:
    """Read the company's 8-Ks of the last KEEP_DAYS days not yet stored, store each verdict. Returns {new, material_new}."""
    from app.services.system_metadata_service import set_value
    cik = await edgar.get_cik(symbol)
    if not cik:
        return {"new": 0, "material_new": 0, "error": "no CIK"}
    since = (today - timedelta(days=KEEP_DAYS)).isoformat()
    rows = [r for r in await stored(db, symbol) if (r.get("filed_on") or "") >= since]
    seen = {r["accession"] for r in rows}
    records, _ = await edgar.get_8k_records_since(cik, since)
    new = material_new = 0
    for rec in records:
        if rec["accession"] in seen or not (items_of(rec) & (ALWAYS | IF_ANNOUNCES)):
            continue
        texts = await edgar.filing_texts(cik, rec["accession"], rec["primary_document"], every_exhibit=True)
        joined = " ".join(t for _, t in texts)
        material, why = verdict(rec, joined)
        rows.append({"accession": rec["accession"], "filed_on": rec["filing_date"], "acceptance": rec.get("acceptance"),
                     "items": rec.get("items"), "material": material, "why": why,
                     "url": filing_url(cik, rec["accession"], rec["primary_document"]),
                     "excerpt": excerpt(texts) if material else None})
        seen.add(rec["accession"])
        new += 1
        material_new += int(material)
    rows.sort(key=lambda r: r.get("filed_on") or "", reverse=True)
    await set_value(db, KEY.format(sym=symbol), json.dumps(rows))
    await db.commit()
    return {"new": new, "material_new": material_new}
