"""Fast-changing figures in a research note (Sam, 2026-11-02: no fast-changing number is ever frozen into a note's text).

A note is written once and read for weeks, so a figure that moves daily (the price and its change over any period, a P/E or any
other multiple, the market value, the move options price, volatility, the 52-week high, a dividend yield) never goes into its text.
The writer types a slot instead, {live:<id>} from SLOTS, as Ask Ivy does with its facts; the stored note keeps the slot, and every
read fills it from the same stored, dated receipts the Overview and the strip show (services/ask_ivy.fact_pack), with each
figure's as-of date for the page's tooltip. A slot whose figure is not on file today takes its sentence out of the note as served,
and so does a slot the writer invented. Durable facts from filings (sales, EPS, margins, segments, guidance, risks) stay written into
the text: they change only when the company files.

The rules, in code (note_rules.note_problems and enforce):
  - typed_fast_figures(sentence): a fast-changing figure typed as a number (FAST_TERM with a digit outside the slots). The draft is
    sent back once with the sentence named; a sentence still typing one is dropped.
  - a sentence with a number slot states no comparison in its own words (TYPED_COMPARISON): "trades at {live:pe}, below its
    history" turns false the day the P/E moves. The comparison comes from a word slot ({live:pe_vs_history} reads "below" or
    "above" today) or not at all.

The checker reads the note with every slot filled, with the figures as EVIDENCE (live_evidence), and its claims are stored with the
slots put back (reslot), so a claim is never served with the day it was checked's value.
"""
from __future__ import annotations

import re

from app.services.note_claims import sentences, words

LIVE = re.compile(r"\{live:([a-z0-9_]+)\}")
NOTE_RULE_VERSION = 4           # 4 (2026-11-02): fast-changing figures only as slots; every note written before it is written again

# slot id: (the receipt's name in the fact pack, what it means, as the writer is told)
SLOTS: dict[str, tuple[str, str]] = {
    "price":            ("last close", "the latest official closing price"),
    "market_value":     ("market cap", "the company's market value"),
    "change_3m":        ("three-month change", "the price change over the last three months"),
    "high_52w":         ("52-week high", "the 52-week high close"),
    "below_52w_high":   ("distance below 52-week high", "how far the price sits below its 52-week high"),
    "volatility_20d":   ("20-day realized volatility", "the 20-day realized volatility, annualized"),
    "pe":               ("P/E", "the trailing P/E"),
    "pe_5y_median":     ("five-year median P/E", "the stock's five-year median P/E"),
    "pe_sector_median": ("sector median P/E", "the median P/E of its GICS sector"),
    "implied_move":     ("report move", "the move options price for the next report"),
}
# word slots: the comparison as the strip states it today (ask_ivy.word_facts), by fact id
WORD_SLOTS: dict[str, tuple[str, str]] = {
    "price_vs_52w_high":  ("price_vs_52_week_high", "the price against its 52-week high, one word (for example below)"),
    "volatility_vs_year": ("volatility_vs_year", "the 20-day volatility against the stock's own past year, one word (for example quiet)"),
    "pe_vs_history":      ("pe_vs_history", "the P/E against its five-year median, one word (for example below)"),
    "pe_vs_sector":       ("pe_vs_sector", "the P/E against its sector median, one word (for example above)"),
}

_DIGIT = re.compile(r"\d")
# a fast-changing figure's words; a sentence holding one with a digit outside the slots types the figure
FAST_TERM = re.compile(
    r"\b(?:share price|stock price|price per share|closing price of (?:the )?(?:stock|shares)|(?<!combined )(?<!aggregate )market cap(?:italization)?"
    r"|(?:its|the company'?s|[A-Z][\w&.]*'s) (?:equity |total )?market value|market value of (?:the company|its (?:common )?(?:stock|shares|equity))"
    r"|(?:stock|shares) (?:has |have )?(?:closed|traded|trades|trade|ended|finished|rose|risen|fell|fallen|gained|lost|declined|climbed"
    r"|dropped|jumped|slid|rallied|returned|outperformed|underperformed)"
    r"|year[- ]to[- ]date (?:return|performance|gain|decline)|total return|price return"
    r"|P\s?/\s?E\b|PE ratio|price[- /]to[- ](?:earnings|sales|book|free cash flow|cash flow)|(?:earnings|sales|EBITDA|valuation) multiples?"
    r"|\bPEG\b|EV\s?/\s?(?:EBITDA|sales|revenue)|times (?:forward |trailing )?(?:earnings|sales|EBITDA)"
    r"|implied (?:move|volatility)|options? (?:market )?(?:prices?|pricing|imply|implies)|straddle|expected move"
    r"|(?:realized|implied|annualized|stock|share|stock price|share price) volatility|volatility of \d"
    r"|52[- ]week|dividend yield|(?:stock|shares) yield)", re.I)
TYPED_COMPARISON = re.compile(
    r"\b(?:above|below|higher|lower|elevated|subdued|cheap|expensive|rich|premium|discount|more than|less than|exceeds?|exceeding"
    r"|near|close to|well off|far from|record)\b", re.I)


def slot_ids(text: str | None) -> list[str]:
    """Pure: the slot ids in a text, in order."""
    return LIVE.findall(text or "")


def known(sid: str) -> bool:
    return sid in SLOTS or sid in WORD_SLOTS


def typed_fast_figure(sentence: str) -> bool:
    """Pure: the sentence types a fast-changing figure as a number (its digits outside the slots)."""
    bare = LIVE.sub("", sentence)
    return bool(FAST_TERM.search(bare) and _DIGIT.search(bare))


def compares_in_words(sentence: str) -> bool:
    """Pure: a sentence with a number slot that compares it in its own words, which a later value can make false."""
    ids = slot_ids(sentence)
    if not any(i in SLOTS for i in ids):
        return False
    return bool(TYPED_COMPARISON.search(LIVE.sub("", sentence)))


def sentence_problems(sentence: str) -> list[str]:
    """Pure: why one sentence breaks the live-figure rules (empty when it keeps them)."""
    out = []
    if typed_fast_figure(sentence):
        out.append("types a fast-changing figure (price, price change, valuation multiple, market value, implied move, volatility, "
                   "52-week figure or dividend yield) as a number: write it as its {live:...} slot")
    bad = [i for i in slot_ids(sentence) if not known(i)]
    if bad:
        out.append(f"uses a slot that does not exist ({', '.join(bad)})")
    if compares_in_words(sentence):
        out.append("compares a live figure in its own words: a later value can make that false; use a word slot or no comparison")
    return out


def prompt_block(available: set[str] | None = None) -> str:
    """The writer's list of slots: names and meanings, never values. `available`: the slot ids whose figure is on file for this stock
    today (the rest are left out, so the writer cannot use a slot that would empty its sentence)."""
    rows = [f"  {{live:{sid}}}  {meaning}" for sid, (_, meaning) in {**SLOTS, **WORD_SLOTS}.items()
            if available is None or sid in available]
    if not rows:
        return "LIVE FIGURES: (none on file for this stock today; state no price, valuation, market value, volatility or options figure)"
    return ("LIVE FIGURES: placeholders for figures that change every day. Never type such a figure; write its placeholder exactly as "
            "shown and the page fills in today's value, with its date, every time the note is read:\n" + "\n".join(rows))


def live_values(facts: list[dict]) -> dict[str, dict]:
    """Pure: slot id -> the fact-pack fact that fills it today ({name, value, as_of, source, kind})."""
    by_name = {f["name"]: f for f in facts if f.get("kind") == "number"}
    by_id = {f["id"]: f for f in facts}
    out = {}
    for sid, (name, _) in SLOTS.items():
        if name in by_name:
            out[sid] = by_name[name]
    for sid, (fid, _) in WORD_SLOTS.items():
        if fid in by_id:
            out[sid] = by_id[fid]
    return out


_ARTICLE = re.compile(r"\b(a|an|A|An)(\s+)([+\-−±]?\d[\d,]*(?:\.\d+)?)")


def _articles(text: str) -> str:
    from app.services.note_rules import _an_for_number
    def art(m: re.Match) -> str:
        want = "an" if _an_for_number(m.group(3).lstrip("+-−±")) and m.group(3)[0].isdigit() else "a"
        return (want.capitalize() if m.group(1)[0].isupper() else want) + m.group(2) + m.group(3)
    return _ARTICLE.sub(art, text)


def fill_sentence(sentence: str, values: dict[str, dict]) -> str | None:
    """Pure: the sentence with every slot filled, or None when one has no figure on file (the sentence is left out)."""
    missing = False
    def sub(m: re.Match) -> str:
        nonlocal missing
        f = values.get(m.group(1))
        if f is None:
            missing = True
            return m.group(0)
        return str(f["value"])
    out = LIVE.sub(sub, sentence)
    return None if missing else _articles(out)


def fill_text(text: str | None, values: dict[str, dict]) -> str | None:
    """Pure: prose with every slot filled, sentences whose slot has no figure left out."""
    if not text or "{live:" not in text:
        return text
    kept = [s for s in (fill_sentence(x, values) for x in sentences(text)) if s is not None]
    return " ".join(kept)


def fill_markdown(content: str | None, values: dict[str, dict]) -> str | None:
    """Pure: the stored markdown note, line by line (headings and bullets kept), filled."""
    if not content or "{live:" not in content:
        return content
    lines = []
    for ln in content.split("\n"):
        if "{live:" not in ln:
            lines.append(ln)
            continue
        m = re.match(r"^(\s*-\s*\*\*[^*]*\*\*\s*)(.*)$", ln)
        head, body = (m.group(1), m.group(2)) if m else ("", ln)
        if "{live:" in head:
            continue                                           # a point whose label holds a slot goes whole
        filled = fill_text(body, values)
        if filled:
            lines.append(head + filled)
    return "\n".join(lines)


def fill_structured(structured: dict | None, values: dict[str, dict]) -> dict | None:
    """Pure: the structured note filled: prose sentences without a figure left out; a point whose label has a slot without one, or
    whose text is left empty, goes whole."""
    if not structured:
        return structured
    s = dict(structured)
    for key in ("bottom_line", "what_they_do"):
        if s.get(key):
            s[key] = fill_text(s[key], values) or ""
    for sec in ("highlights", "watch", "risks"):
        pts = []
        for p in s.get(sec) or []:
            if not isinstance(p, dict):
                continue
            lead = fill_sentence(p.get("lead") or "", values)
            detail = fill_text(p.get("detail") or "", values)
            if lead is None or not detail:
                continue
            pts.append({**p, "lead": lead, "detail": detail})
        s[sec] = pts
    return s


def used_inputs(structured: dict | None, content: str | None, values: dict[str, dict]) -> list[dict]:
    """Pure: the receipts behind the slots a note uses ({name, value, as_of, source}), once each, for the page's tooltips."""
    seen, out = set(), []
    texts = [content or ""]
    s = structured or {}
    texts += [s.get("bottom_line") or "", s.get("what_they_do") or ""]
    texts += [f"{p.get('lead', '')} {p.get('detail', '')}" for sec in ("highlights", "watch", "risks") for p in (s.get(sec) or []) if isinstance(p, dict)]
    for sid in (i for t in texts for i in slot_ids(t)):
        f = values.get(sid)
        if f is None or sid in seen:
            continue
        seen.add(sid)
        out.append({"name": f["name"], "value": str(f["value"]), "as_of": f.get("as_of"), "source": f.get("source")})
    return out


def live_evidence(values: dict[str, dict]) -> str:
    """The figures the checker may confirm a filled slot against: name, value and date."""
    if not values:
        return "(none)"
    return "\n".join(f"  {f['name']}: {f['value']}" + (f" (as of {str(f['as_of'])[:10]})" if f.get("as_of") else "")
                     for f in values.values())


def reslot(verification: dict | None, slotted_text: str, values: dict[str, dict]) -> dict | None:
    """Pure: the checker's claims with the slots put back. Each claim copied a sentence of the filled note; the sentence it came from
    is found among the slotted note's sentences by their filled words, and the claim's own words get that sentence's slots back."""
    if not verification or not isinstance(verification.get("claims"), list) or "{live:" not in (slotted_text or ""):
        return verification
    pairs = []
    for ln in slotted_text.split("\n"):
        body = re.sub(r"^[-*#\s]+|\*\*", "", ln).strip()
        for s in sentences(body):
            if "{live:" in s:
                filled = fill_sentence(s, values)
                if filled is not None:
                    pairs.append((" ".join(words(filled)), s))
    claims = []
    for c in verification["claims"]:
        c = dict(c) if isinstance(c, dict) else c
        if isinstance(c, dict):
            copied = " ".join(words(c.get("sentence")))
            for filled_words, s in pairs:
                if copied and (copied == filled_words or copied in filled_words):
                    c["sentence"] = s
                    claim = str(c.get("claim") or "")
                    for sid in slot_ids(s):
                        v = values.get(sid)
                        if v is not None and str(v["value"]) in claim:
                            claim = claim.replace(str(v["value"]), f"{{live:{sid}}}", 1)
                    c["claim"] = claim
                    break
        claims.append(c)
    return {**verification, "claims": claims}


def fill_verification(verification: dict | None, values: dict[str, dict]) -> dict | None:
    """Pure: the served claims with today's figures in their words (a claim whose slot has no figure today is left out)."""
    if not verification or not isinstance(verification.get("claims"), list):
        return verification
    out = []
    for c in verification["claims"]:
        if not isinstance(c, dict) or "{live:" not in f"{c.get('claim', '')}{c.get('sentence', '')}":
            out.append(c)
            continue
        claim, sent = fill_sentence(str(c.get("claim") or ""), values), fill_sentence(str(c.get("sentence") or ""), values)
        if claim is None or sent is None:
            continue
        out.append({**c, "claim": claim, "sentence": sent})
    return {**verification, "claims": out}


_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
CACHE_SECONDS = 600                 # a note page read refills from receipts at most this old


async def values_for(db, symbol: str) -> dict[str, dict]:
    """Today's figures for a stock's slots, from the fact pack (database reads only), cached CACHE_SECONDS per stock and New York day."""
    import time
    from app.services.chart_markers import today_ny
    key = (symbol, today_ny().isoformat())
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    from app.services.ask_ivy import fact_pack
    try:
        pack = await fact_pack(db, symbol, today_ny())
        vals = live_values(pack["facts"])
    except Exception as exc:                 # no receipts today: every slot sentence is left out, never a guess
        from app.services.redact import redact
        print(f"[note_live] {symbol}: no live figures ({redact(exc)[:120]})", flush=True)
        vals = {}
    _CACHE[key] = (time.monotonic(), vals)
    return vals


def keep_available(structured: dict, values: dict[str, dict]) -> dict:
    """Pure: the note as stored, slots kept, without the sentences whose slot has no figure on file as it is written (the prompt names
    only the available slots; one the writer used anyway would empty its sentence at every read)."""
    s = dict(structured)
    for key in ("bottom_line", "what_they_do"):
        if s.get(key):
            s[key] = " ".join(x for x in sentences(s[key]) if fill_sentence(x, values) is not None)
    for sec in ("highlights", "watch", "risks"):
        pts = []
        for p in s.get(sec) or []:
            if not isinstance(p, dict) or fill_sentence(p.get("lead") or "", values) is None:
                continue
            detail = " ".join(x for x in sentences(p.get("detail") or "") if fill_sentence(x, values) is not None)
            if detail:
                pts.append({**p, "detail": detail})
        s[sec] = pts
    return s
