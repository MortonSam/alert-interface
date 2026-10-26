"""Ivy's Read in plain English (Sam, 2026-10-22): a short note that teaches, like the walkthrough, not a trader's note.

At most MAX_SENTENCES sentences: what the options expect (percent, dollars, by when), then how much of that is the report and how it
compares with the stock's typical report move, then whether the stock has been calmer or busier than usual lately. Every figure and
every label comes from the page's own facts (`page_facts`): the Details figures (expected move, report move), the verdict's typical
move and comparison words (services/move_comparison), and the band words the Details rows print (thresholds.spread_label's cutoffs
for the spread row, thresholds.rv_rank_label for the RV rank row).

    page_facts(...)            the facts and the band words, from the same values the page shows
    build_prompt(facts)        the writing prompt, its figures pre-written as lines the model copies
    read_problems(text, facts) every deterministic rule a read breaks (length, jargon, advice, figures, order)
    band_contradictions(text, facts)  where a read contradicts the page's band words (also validate_data.check_options_read_bands)
    verification_prompt / parse_verdicts  the claim verifier, one verdict per sentence
    write_read(facts)          write, check and verify, ROUNDS rounds at most; a read that fails is never served
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import date

from app.services.move_comparison import COMPARISON_WORDS
from app.thresholds import SPREAD_CHEAP_PP, SPREAD_RICH_PP, rv_rank_label

READ_PLAIN_VERSION = 1
MAX_SENTENCES = 4
MAX_WORDS = 90
ROUNDS = 3
CALL_SECONDS = 90
READ_FAILED_CHECKS = "Ivy's Read for today's options data did not pass its checks"
# draft wording, held for Sam: no expected move (the Details panel says "Implied move unavailable"), so nothing to lead with
READ_NO_MOVE = "Today's options data gives no expected move, so there is no read"

# The words a newcomer can't read; each is allowed only in a sentence that also explains it (JARGON_GLOSS)
JARGON = {
    "IV": r"\bIVs?\b", "RV": r"\bRVs?\b", "pp": r"\d\s*pp\b|\bpp\b", "ATM": r"\bATM\b|\bat[- ]the[- ]money\b",
    "vol": r"\bvol\b|\bvols\b", "premium": r"\bpremiums?\b", "rich": r"\brich\b", "cheap": r"\bcheap(?:er|ly)?\b",
    "volatility": r"\bvolatility\b", "straddle": r"\bstraddles?\b",
}
# what counts as explaining it in the same sentence: the plain words beside it
JARGON_GLOSS = {
    "IV": r"options? (?:expect|price)", "RV": r"actually (?:swung|moved)", "pp": r"$^", "ATM": r"nearest (?:to )?(?:today's|the current) price",
    "vol": r"$^", "premium": r"(?:price|cost) (?:of|paid for) (?:an |the )?options?", "rich": r"more swing than",
    "cheap": r"less swing than", "volatility": r"\bsw(?:ing|ung)\b|\bmove[sd]?\b", "straddle": r"a call and a put",
}
NEVER = {
    "edge": r"\bedges?\b",
    "advice": r"\byou (?:should|could|might|may want)\b|\b(?:should|consider|worth) (?:buy|sell|own|trade|play)|\brecommend",
    "buyers or sellers": r"\b(?:option |premium )?(?:buyers?|sellers?|writers?)\b",
    "a trade": r"\b(?:opportunity|bet|wager|position(?:ing)?|play(?:ing)? (?:it|the)|favou?rs? (?:buying|selling))\b",
}
# band words: what a read may not say when the page's row says otherwise
_PRICEY = r"\b(?:pricey|expensive|rich|costly|overpriced|elevated (?:option )?prices?|pay(?:ing)? up|a lot for)\b"
_CHEAP = r"\b(?:cheap(?:er)?|inexpensive|underpriced|bargain|on sale|a little for)\b"
_BUSIER = r"\b(?:busier|choppier|jumpier|livelier|wilder|more volatile|more turbulent|swinging more|swung more|moving more|elevated|extreme)\b"
_CALMER = r"\b(?:calmer|quieter|steadier|more subdued|subdued|swinging less|swung less|moving less|quiet)\b"
_MORE = r"\b(?:more than|bigger than|larger than|above|exceeds?|higher than)\b"
_LESS = r"\b(?:less than|smaller than|below|under|lower than)\b"
_SAME = r"\b(?:about the same|in line with|similar to|close to|roughly (?:the same|equal))\b"


def spread_word(spread_pp: float | None) -> str | None:
    """The spread row's word (frontend lib/optionsRows.spreadRowValue): pricey, cheap or about the same, by the same cutoffs."""
    if spread_pp is None:
        return None
    return "pricey" if spread_pp > SPREAD_RICH_PP else "cheap" if spread_pp < SPREAD_CHEAP_PP else "about the same"


LATELY = {"quiet": "calmer than usual", "normal": "about as busy as usual", "elevated": "busier than usual", "extreme": "much busier than usual"}


def _day(d: str | date | None) -> str | None:
    if not d:
        return None
    d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    return d.strftime("%b %-d, %Y")


def page_facts(*, symbol: str, name: str, fact_values: dict, report: dict | None) -> dict:
    """Pure: the read's facts from the page's own values. `fact_values` is the options read's fact block (the Details figures and
    rows read it); `report` is the expected-move endpoint's report fields (routers/tickers._report_move_fields)."""
    report = report or {}
    # the RV rank row's band (frontend lib/optionsRows.rankRowValue, 2026-10-26): the percentile of days, rounded down, by the rank
    # cutoffs; hidden, like the row, while the rank itself is held
    rank, pctl = fact_values.get("rv_rank"), fact_values.get("rv_percentile")
    band = rv_rank_label(math.floor(pctl)).label if rank is not None and pctl is not None else None
    rpct = report.get("report_move_pct") if report.get("report_move_state") == "ok" else None
    rm = report.get("report_move") or {}
    return {
        "symbol": symbol, "name": name,
        "total_pct": fact_values.get("expected_move_pct"), "total_dollars": fact_values.get("expected_move_dollars"),
        "expiration": fact_values.get("expiration_used"), "chain_date": fact_values.get("chain_date"),
        "report_pct": rpct, "report_date": rm.get("report_date") if rpct is not None else None,
        "typical_pct": report.get("typical_move_pct") if rpct is not None else None,
        "typical_n": report.get("typical_n") if rpct is not None else None,
        "comparison": report.get("move_comparison") if rpct is not None else None,
        "rv_rank": rank, "swing_band": band, "lately": LATELY.get(band) if band else None,
        "spread_pp": fact_values.get("iv_rv_spread_pp"), "spread_word": spread_word(fact_values.get("iv_rv_spread_pp")),
    }


def fact_lines(f: dict) -> dict[str, str]:
    """The lines the model copies figures from, keyed A to E. A line is absent when its fact is."""
    out: dict[str, str] = {}
    if f.get("total_pct") is not None and f.get("expiration"):
        dol = f" (${f['total_dollars']:.2f} either way)" if f.get("total_dollars") is not None else ""
        out["A"] = f"Options price a move of ±{f['total_pct'] * 100:.1f}%{dol} by {_day(f['expiration'])}."
    if f.get("report_pct") is not None:
        on = f" on {_day(f['report_date'])}" if f.get("report_date") else ""
        out["B"] = f"About {f['report_pct'] * 100:.1f}% of that comes from the report{on}; the rest is the stock's ordinary day-to-day swing."
        if f.get("typical_pct") and f.get("comparison") in COMPARISON_WORDS:
            out["C"] = (f"On a typical report the stock has moved {f['typical_pct']:.1f}% on the first day, over {f['typical_n']} reports; "
                        f"the report move is {COMPARISON_WORDS[f['comparison']]} that.")
    if f.get("lately"):
        out["D"] = f"Lately the stock has been {f['lately']} for it, against its past year."
    if f.get("spread_word"):
        out["E"] = (f"Options expect {abs(f['spread_pp']):.1f} points {'more' if f['spread_pp'] > 0 else 'less'} swing than the stock has shown "
                    f"lately, so they look {f['spread_word']}.") if f["spread_word"] != "about the same" \
            else "Options expect about the same swing the stock has shown lately."
    return out


def build_prompt(f: dict) -> str:
    lines = fact_lines(f)
    shown = "\n".join(f"{k}. {v}" for k, v in lines.items())
    order = ["Sentence 1 states line A: what the options expect, in percent and dollars, and by when. It may say in a few words that the"
             " move could go either way; no other sentence explains or repeats line A."]
    if "B" in lines:
        order.append("The next sentence states line B" + (" and compares it with line C, in the same sentence." if "C" in lines else "."))
    if "E" in lines:
        order.append("If you use line E, it is one sentence after that.")
    if "D" in lines:
        order.append("The last sentence states line D: whether the stock has been calmer or busier than usual lately.")
    n = 1 + ("B" in lines) + ("D" in lines)
    return f"""You are Ivy, writing a short note about {f['name']} ({f['symbol']}) options for someone who has never traded options.
Teach in plain, calm English, the way the site's walkthrough does: no greeting, no exclamation, no slang.

THE PAGE'S OWN FACTS (copy every figure exactly as written here; use no other number):
{shown}

WRITE
- At most {MAX_SENTENCES} sentences and {MAX_WORDS} words, as one short paragraph. No lists, headings or dashes.
{chr(10).join('- ' + o for o in order)}
- Every sentence states a fact from a line that no earlier sentence used. Never explain, rephrase or expand an earlier sentence: with
  nothing new to say, stop. With these lines that is {n} sentence{'s' if n > 1 else ''}, or {n + 1} with line E.
- Line E says whether options look pricey or cheap against the stock's recent swings. You may leave it out. If you use it, say
  exactly what it says and why; never call options expensive, pricey or cheap when it says "about the same".
- Write every date exactly as the lines do ("Nov 20, 2026"), and the move with the ± sign as line A does.
- Never mention "the page", these lines or where the facts come from.
- Never use: IV, RV, implied volatility, realized volatility, vol, pp, ATM, at-the-money, straddle, premium, rich, edge.
- No advice. Never say what anyone should do, never mention buyers or sellers of options, never call anything an opportunity or a
  bet. Describe what the options expect, nothing more.
- No dates, figures, causes or forecasts that the lines do not state.

Output the note only."""


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", (text or "").strip()) if s.strip()]


_NUM = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def _numbers(text: str) -> set[str]:
    return {m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else "") for m in _NUM.finditer(text or "")}


_NEGATION = re.compile(r"\b(?:not|no|neither|nor|never|far from|isn't|aren't|wasn't|hasn't)\b(?:\W+\w+){0,3}\W*$", re.I)


def _says(pat: str, text: str) -> bool:
    """A band word `text` asserts: a match not negated by the four words before it ("neither cheap nor rich", "far from extreme")."""
    return any(not _NEGATION.search(text[:m.start()]) for m in re.finditer(pat, text or "", re.I))


_SPREAD_WORDS = r"\b(?:pricey|cheap|expensive|points? (?:more|less)|about the same swing|in line with|same (?:swing|amount)|lines up)\b"


def lines_stated(sentence: str, f: dict) -> set[str]:
    """Pure: which fact lines (A to E) a sentence states: its figures, or its words for D and E."""
    nums, out = _numbers(sentence), set()
    a_figs = {f"{f['total_pct'] * 100:.1f}"} if f.get("total_pct") is not None else set()
    if f.get("total_dollars") is not None:
        a_figs.add(f"{f['total_dollars']:.2f}")
    if a_figs & nums:
        out.add("A")
    if f.get("report_pct") is not None and f"{f['report_pct'] * 100:.1f}" in nums:
        out.add("B")
    if f.get("typical_pct") and f"{f['typical_pct']:.1f}" in nums:
        out.add("C")
    lately = re.search(_BUSIER, sentence, re.I) or re.search(_CALMER, sentence, re.I) or re.search(r"\bas (?:busy|much) as usual\b|\busual\b", sentence, re.I)
    if lately and not re.search(r"\btypical report\b", sentence, re.I):
        out.add("D")
    if re.search(_SPREAD_WORDS, sentence, re.I):
        out.add("E")
    return out


def restatements(text: str, f: dict) -> list[int]:
    """Pure: the 1-based numbers of the sentences that state no line an earlier sentence had not (a restatement or a filler)."""
    seen: set[str] = set()
    out = []
    for i, s in enumerate(sentences(text), 1):
        new = lines_stated(s, f) - seen
        if not new:
            out.append(i)
        seen |= lines_stated(s, f)
    return out


def band_contradictions(text: str, f: dict) -> list[str]:
    """Where `text` contradicts the page's band words: the spread row (pricey / cheap / about the same), the lately band (from the RV
    rank row) and the report move's comparison with the typical report move. Pure; validate_data runs it over cached reads."""
    out = []
    t = text or ""
    sw = f.get("spread_word")
    if sw == "about the same" and (_says(_PRICEY, t) or _says(_CHEAP, t)):
        out.append(f"it calls options {'pricey' if _says(_PRICEY, t) else 'cheap'} where the page says they expect about the same swing the stock has shown")
    if sw == "pricey" and _says(_CHEAP, t):
        out.append("it calls options cheap where the page says pricey")
    if sw == "cheap" and _says(_PRICEY, t):
        out.append("it calls options pricey where the page says cheap")
    band = f.get("swing_band")
    if band in ("quiet", "normal") and _says(_BUSIER, t):
        out.append(f"it says the stock has been busier than usual where the page's band is {band}")
    if band in ("elevated", "extreme", "normal") and _says(_CALMER, t):
        out.append(f"it says the stock has been calmer than usual where the page's band is {band}")
    if f.get("typical_pct") and f.get("comparison"):
        typ = f"{f['typical_pct']:.1f}"
        for s in sentences(t):
            if typ not in _numbers(s):
                continue
            said = "more than usual" if _says(_MORE, s) else "less than usual" if _says(_LESS, s) else \
                "about its usual" if _says(_SAME, s) else None
            if said and said != f["comparison"]:
                out.append(f"it says the report move is {said.replace(' usual', '').replace('about its', 'about the same as')} the typical report move where the page says {COMPARISON_WORDS[f['comparison']]}")
    return out


def read_problems(text: str, f: dict) -> list[str]:
    """Every deterministic rule the read breaks. Empty means it may go to the verifier."""
    out: list[str] = []
    ss = sentences(text)
    if not ss:
        return ["it is empty"]
    if len(ss) > MAX_SENTENCES:
        out.append(f"it has {len(ss)} sentences, more than {MAX_SENTENCES}")
    if len((text or "").split()) > MAX_WORDS:
        out.append(f"it has more than {MAX_WORDS} words")
    if re.search(r"[–—]|^\s*[-*•]", text, re.M):
        out.append("it uses a dash or a list")
    if re.search(r"\b(?:January|February|March|April|June|July|August|September|October|November|December)\b", text):
        out.append('it writes a month in full where the page writes it short ("Nov 20, 2026")')
    if re.search(r"\b(?:the|this) page\b|\bthe lines?\b|\bthe facts\b", text, re.I):
        out.append("it mentions where its facts come from")
    for s in ss:
        for word, pat in JARGON.items():
            if re.search(pat, s, re.I if word not in ("IV", "RV", "ATM") else 0) and not re.search(JARGON_GLOSS[word], s, re.I):
                out.append(f'it uses "{word}" without explaining it in the same sentence')
        for what, pat in NEVER.items():
            if re.search(pat, s, re.I):
                out.append(f"it mentions {what}")
    lines = fact_lines(f)
    allowed = set().union(*(_numbers(v) for v in lines.values())) if lines else set()
    extra = sorted(_numbers(text) - allowed)
    if extra:
        out.append(f"it states figures the page's facts do not: {', '.join(extra)}")
    if "A" in lines:
        need = _numbers(lines["A"])
        if not need <= _numbers(ss[0]):
            out.append("it does not lead with what options expect in percent and dollars and by when (line A)")
    if "B" in lines and f"{f['report_pct'] * 100:.1f}" not in _numbers(text):
        out.append("it leaves out how much of the move is the report (line B)")
    if "C" in lines and f"{f['typical_pct']:.1f}" not in _numbers(text):
        out.append("it leaves out the typical report move (line C)")
    if "D" in lines and not (re.search(_BUSIER, ss[-1], re.I) or re.search(_CALMER, ss[-1], re.I) or re.search(r"\b(?:usual|normal)\b", ss[-1], re.I)):
        out.append("its last sentence does not say whether the stock has been calmer or busier than usual (line D)")
    for i in restatements(text, f):
        out.append(f"sentence {i} restates an earlier sentence: it states no fact the earlier sentences had not")
    out += band_contradictions(text, f)
    return list(dict.fromkeys(out))


def verification_prompt(f: dict, text: str) -> str:
    lines = fact_lines(f)
    numbered = "\n".join(f"s{i}: {s}" for i, s in enumerate(sentences(text), 1))
    return f"""You are a rigorous fact-checker. Check each sentence of a short note about {f['name']} ({f['symbol']}) options against these facts ONLY.
Use no outside knowledge.

FACTS:
{chr(10).join(f'{k}. {v}' for k, v in lines.items())}

SENTENCES:
{numbered}

RULES
- "supported": every figure, date and claim in it is stated in the facts, with the same meaning. Plain-English rewording of a fact is fine.
- "contradicted": it conflicts with a fact, including calling options pricey, expensive or cheap when line E does not say so, saying the
  stock has been busier or calmer than line D says, or comparing the report move with the typical move differently from line C.
- "unsupported": it says anything the facts do not state: a cause, a forecast, a figure, advice, what buyers or sellers do, or a judgment
  of whether the options are worth buying or selling.
- Bias toward "unsupported" when in doubt.

Return JSON only: {{"verdicts": [{{"id": "s1", "status": "supported|unsupported|contradicted", "reason": "one sentence"}}]}}"""


def parse_verdicts(content: str) -> dict[str, dict]:
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        rows = (json.loads(m.group(0)).get("verdicts") or []) if m else []
    except ValueError:
        rows = []
    return {str(r.get("id")).strip(): {"status": r.get("status"), "reason": r.get("reason")} for r in rows if isinstance(r, dict)}


def verdict_problems(text: str, verdicts: dict[str, dict]) -> list[str]:
    out = []
    for i, s in enumerate(sentences(text), 1):
        v = verdicts.get(f"s{i}")
        if not v:
            out.append(f"the verifier gave no verdict on sentence {i}")
        elif v.get("status") != "supported":
            out.append(f"sentence {i} is {v.get('status')}: {v.get('reason')}")
    return out


async def write_read(f: dict, *, client=None) -> dict:
    """{result: passed|failed, content, problems, verdicts, attempts, model, cost_usd}. Writes nothing."""
    from app.services.research_cost import estimate_cost_usd
    if client is None:
        from app.services.anthropic_client import AnthropicClient
        client = AnthropicClient()
    out = {"result": "failed", "content": None, "problems": [], "verdicts": {}, "attempts": 0, "model": None, "cost_usd": 0.0, "drafts": []}
    if "A" not in fact_lines(f):             # no expected move: the read would have nothing true to lead with (CMS, 2026-10-26)
        out.update(result="no_move", problems=["no expected move in the page's facts"])
        return out

    def charge(gen: dict) -> None:
        out["cost_usd"] += estimate_cost_usd(gen["model_used"], gen["input_tokens"], gen["output_tokens"]) or 0.0

    prompt, reasons = build_prompt(f), []
    for attempt in range(1, ROUNDS + 1):
        out["attempts"] = attempt
        ask = prompt if attempt == 1 else (prompt + "\n\nYour previous note was rejected for these reasons: " + "; ".join(reasons)
                                           + ". Rewrite it so none applies.")
        gen = await asyncio.wait_for(client.generate_options_read(ask), CALL_SECONDS)
        out["model"] = gen["model_used"]
        charge(gen)
        text = re.sub(r"\s+", " ", gen["content"]).strip()
        out["drafts"].append(text)
        reasons = read_problems(text, f)
        if not reasons:
            ver = await asyncio.wait_for(client.verify_research_note(verification_prompt(f, text)), CALL_SECONDS)
            charge(ver)
            out["verdicts"] = parse_verdicts(ver["content"])
            reasons = verdict_problems(text, out["verdicts"])
        if not reasons:
            out.update(result="passed", content=text, problems=[])
            return out
        out["problems"] = reasons
    return out
