"""Ivy's Read in plain English, built from the page's own facts with no model call (Sam, 2026-10-27).

Each read is the approved lines in order, each present only when the page has its fact: the move (line A, with the company's
short name); the span sentence (line S) when the move is not the report's alone; the report share in Sherwin-Williams' form (line B)
on a company-confirmed date with a separated report move, else the typical first-day move (line C); whether options expect more,
less or about the same swing as the stock has shown lately (line E); and whether the stock has been calmer or busier than usual
(line D). Every figure and every label comes from the page's own facts (`page_facts`): the Details figures (expected move, report
move), the verdict's typical move and comparison words (services/move_comparison), and the band words the Details rows print
(thresholds.spread_label's cutoffs for the spread row, thresholds.rv_rank_label for the RV rank row).

    page_facts(...)            the facts and the band words, from the same values the page shows
    fact_lines(facts)          the approved lines, keyed A, S, B, C, E, D
    compose_read(facts)        the read: the lines in order
    read_problems(text, facts) every deterministic rule a read breaks (length, jargon, advice, figures, order); run on every read
    band_contradictions(text, facts)  where a read contradicts the page's band words (also validate_data.check_options_read_bands)
    write_read(facts)          compose and check; a read that fails is never served
"""
from __future__ import annotations

import math
import re
from datetime import date

from app.services.move_comparison import COMPARISON_WORDS
from app.thresholds import SPREAD_CHEAP_PP, SPREAD_RICH_PP, rv_rank_label

READ_PLAIN_VERSION = 4           # 2 (2026-10-26): typical move and the more/less/same swing line required; report share only on a company-confirmed date
                                 # 3 (Sam, 2026-10-26 evening): the span sentence (line S), line D's words, line B ends with the comparison
                                 # 4 (Sam, 2026-10-27): the lines themselves, no model; line A names the company
MAX_SENTENCES = 5                # A, S, C, E, D without a report share; A, B, E, D with one
SPAN_TRADING_DAYS = 2            # Sam (2026-10-26): an expiration more than this many trading days after the report covers more than the report
SPAN = "That covers every trading day until then"
SPAN_TAIL = ", not just the report day"
MAX_WORDS = 100
READ_MODEL = "deterministic"     # model_used on a cached read: built from the page's lines, no model
READ_FAILED_CHECKS = "Ivy's Read for today's options data did not pass its checks"
# Sam's approved words (2026-10-26), verbatim: no expected move (the Details panel says "Implied move unavailable"), so nothing to lead with
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
# clauses that only restate the move (Sam, 2026-10-26): the ± sign already says it could go either way
RESTATING = {
    "meaning": r"\bmeaning\b|\bwhich means\b|\bin other words\b|\bthat is,",
    "either direction": r"\beither (?:direction|way)\b|\bup or down\b|\bhigher or lower\b|\bin both directions\b",
    "no indication": r"\bno (?:indication|sign|hint)\b|\bwithout (?:saying|indicating)\b",
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
SWING = {"pricey": "more swing than", "cheap": "less swing than", "about the same": "about the same swing as"}


def _day(d: str | date | None) -> str | None:
    if not d:
        return None
    d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    return d.strftime("%b %-d, %Y")


def page_facts(*, symbol: str, name: str, fact_values: dict, report: dict | None) -> dict:
    """Pure: the read's facts from the page's own values. `fact_values` is the options read's fact block (the Details figures and
    rows read it); `report` is the expected-move endpoint's report fields (routers/tickers._report_move_fields). The report share is
    used only on a company-confirmed date (`report_confirmed`); the typical first-day move is the verdict's with a report, else the
    Details line's ("One-day earnings moves: avg ±6.5% ... over 21 prints", avg_earnings_1d_move_pct)."""
    from app.services.briefing import short_name
    report = report or {}
    # the RV rank row's band (frontend lib/optionsRows.rankRowValue, 2026-10-26): the percentile of days, rounded down, by the rank
    # cutoffs; hidden, like the row, while the rank itself is held
    rank, pctl = fact_values.get("rv_rank"), fact_values.get("rv_percentile")
    band = rv_rank_label(math.floor(pctl)).label if rank is not None and pctl is not None else None
    rpct = report.get("report_move_pct") if report.get("report_move_state") == "ok" and report.get("report_confirmed") else None
    rm = report.get("report_move") or {}
    comparison = report.get("move_comparison") if rpct is not None else None
    typical, typical_n = (report.get("typical_move_pct"), report.get("typical_n")) if rpct is not None else (None, None)
    if typical is None and fact_values.get("avg_earnings_1d_move_pct") is not None and (fact_values.get("earnings_sample_size") or 0) >= MIN_TYPICAL_N:
        typical, typical_n = fact_values["avg_earnings_1d_move_pct"], fact_values["earnings_sample_size"]
    return {
        "symbol": symbol, "name": short_name(name, symbol) or name,
        "total_pct": fact_values.get("expected_move_pct"), "total_dollars": fact_values.get("expected_move_dollars"),
        "expiration": fact_values.get("expiration_used"), "chain_date": fact_values.get("chain_date"),
        "report_pct": rpct, "report_date": rm.get("report_date") if rpct is not None else None,
        "typical_pct": typical, "typical_n": typical_n,
        "comparison": comparison,
        "span": span_line(rpct, report.get("report_confirmed"), fact_values.get("next_earnings_date"), fact_values.get("expiration_used")),
        "rv_rank": rank, "swing_band": band, "lately": LATELY.get(band) if band else None,
        "spread_pp": fact_values.get("iv_rv_spread_pp"), "spread_word": spread_word(fact_values.get("iv_rv_spread_pp")),
    }


MIN_TYPICAL_N = 3          # the Details line shows the one-day history from 3 reports (frontend lib/freshness.oneDayHistoryLine)


def _trading_days_after(start: date, end: date) -> int:
    from datetime import timedelta
    from app.services.trading_calendar import is_trading_day
    return sum(is_trading_day(start + timedelta(days=i)) for i in range(1, (end - start).days + 1))


def span_line(report_pct, confirmed, report_date, expiration) -> str | None:
    """Pure: line S (Sam, 2026-10-26), said when the read has no report share and the move is not the report's alone: no
    company-confirmed date, or an expiration more than SPAN_TRADING_DAYS trading days after it. "Not just the report day" only when a
    report date falls on or before the expiration."""
    if report_pct is not None or not expiration:
        return None
    exp = date.fromisoformat(str(expiration)[:10])
    rd = date.fromisoformat(str(report_date)[:10]) if report_date else None
    if confirmed and rd and rd <= exp and _trading_days_after(rd, exp) <= SPAN_TRADING_DAYS:
        return None
    return SPAN + (SPAN_TAIL if rd and rd <= exp else "") + "."


def fact_lines(f: dict) -> dict[str, str]:
    """The lines the model copies figures from, keyed A to E. A line is absent when its fact is."""
    out: dict[str, str] = {}
    if f.get("total_pct") is not None and f.get("expiration"):
        dol = f" (${f['total_dollars']:.2f})" if f.get("total_dollars") is not None else ""
        out["A"] = f"Options on {f['name']} price a move of ±{f['total_pct'] * 100:.1f}%{dol} by {_day(f['expiration'])}."
        if f.get("span"):
            out["S"] = f["span"]
    if f.get("report_pct") is not None:
        on = f" on {_day(f['report_date'])}" if f.get("report_date") else ""
        out["B"] = f"About {f['report_pct'] * 100:.1f}% of that move comes from the report{on}."
        if f.get("typical_pct") and f.get("comparison") in COMPARISON_WORDS:     # Sam (2026-10-26): B ends with the page's comparison word
            out["B"] = out["B"][:-1] + (f", {COMPARISON_WORDS[f['comparison']]} its typical first-day move of {f['typical_pct']:.1f}%"
                                        f" over {f['typical_n']} reports.")
    if f.get("typical_pct") and not ("B" in out and f.get("comparison") in COMPARISON_WORDS):
        out["C"] = f"On its past report days the stock has moved {f['typical_pct']:.1f}% on the first day on average, over {f['typical_n']} reports."
    if f.get("lately"):
        out["D"] = f"Lately it has been {f['lately']} compared with its past year."
    if f.get("spread_word"):
        out["E"] = f"Options expect {SWING[f['spread_word']]} the stock has shown lately."
    return out


ORDER = ("A", "S", "B", "C", "E", "D")


def compose_read(f: dict) -> str:
    """Pure: the read, the page's lines in order (Sam, 2026-10-27)."""
    lines = fact_lines(f)
    return " ".join(lines[k] for k in ORDER if k in lines)


_SPLIT = re.compile(r"(?<=[.!?])(?<!\b[A-Z]\.)\s+(?=[A-Z\"'(])")     # never after an initial ("Arthur J. Gallagher", "U.S. Bancorp")


def sentences(text: str, name: str | None = None) -> list[str]:
    """The text's sentences. The company's own name is never split ("Yum! Brands", "W. R. Berkley"), nor is an initial."""
    t = (text or "").strip()
    if name and name in t:
        t = t.replace(name, "\x00")
    return [s.strip().replace("\x00", name or "") for s in _SPLIT.split(t) if s.strip()]


_NUM = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def _numbers(text: str) -> set[str]:
    return {m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else "") for m in _NUM.finditer(text or "")}


_NEGATION = re.compile(r"\b(?:not|no|neither|nor|never|far from|isn't|aren't|wasn't|hasn't)\b(?:\W+\w+){0,3}\W*$", re.I)


def _says(pat: str, text: str) -> bool:
    """A band word `text` asserts: a match not negated by the four words before it ("neither cheap nor rich", "far from extreme")."""
    return any(not _NEGATION.search(text[:m.start()]) for m in re.finditer(pat, text or "", re.I))


_SPREAD_WORDS = r"\b(?:pricey|cheap|expensive|points? (?:more|less)|(?:more|less|bigger|smaller|larger) (?:swing|movement|moves?)|about the same (?:swing|amount)|in line with|same (?:swing|amount)|lines up)\b"


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
    spread = re.search(_SPREAD_WORDS, sentence, re.I)
    rest = re.sub(_SPREAD_WORDS + r"[^.]*", "", sentence, flags=re.I) if spread else sentence
    lately = re.search(_BUSIER, rest, re.I) or re.search(_CALMER, rest, re.I) or re.search(r"\bas (?:busy|much) as usual\b|\busual\b|\busual pace\b", rest, re.I)
    if lately and not re.search(r"\b(?:typical|past) report\b|\breport days?\b", rest, re.I):
        out.add("D")
    if spread:
        out.add("E")
    if SPAN.lower()[5:] in sentence.lower():          # "covers every trading day until then"
        out.add("S")
    return out


def restatements(text: str, f: dict) -> list[int]:
    """Pure: the 1-based numbers of the sentences that state no line an earlier sentence had not (a restatement or a filler)."""
    seen: set[str] = set()
    out = []
    for i, s in enumerate(sentences(text, f.get("name")), 1):
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
    if sw and sw != "about the same" and re.search(r"\babout the same (?:swing|amount)\b", t, re.I):
        out.append(f"it says options expect about the same swing where the page says {sw}")
    if sw != "pricey" and _says(r"\bmore (?:swing|movement)\b", t):
        out.append("it says options expect more swing than the stock has shown where the page does not")
    if sw != "cheap" and _says(r"\bless (?:swing|movement)\b", t):
        out.append("it says options expect less swing than the stock has shown where the page does not")
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
        for s in sentences(t, f.get("name")):
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
    ss = sentences(text, f.get("name"))
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
        for what, pat in RESTATING.items():
            if re.search(pat, s, re.I):
                out.append(f'it restates the move ("{what}"): the ± sign already says it')
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
    if "S" in lines and not any(lines["S"][5:-1].lower() in s.lower() for s in ss[:2]):
        out.append(f'it does not say, right after the move, "{lines["S"]}" (line S)')
    if "B" in lines and "typical" in lines["B"]:
        bs = [s for s in ss if f"{f['report_pct'] * 100:.1f}" in _numbers(s)]
        tail = lines["B"].split(", ", 1)[-1][:-1]
        if not bs or "of that move comes from the report" not in bs[0] or not bs[0].rstrip(".").endswith(tail):
            out.append(f'its report sentence is not line B\'s form, ending "{tail}" (line B)')
    if f.get("typical_pct") and f"{f['typical_pct']:.1f}" not in _numbers(text):
        out.append("it leaves out the typical report move (line C)")
    if "E" in lines and not any("E" in lines_stated(s, f) for s in ss):
        out.append("it leaves out whether options expect more, less or about the same swing as the stock has shown lately (line E)")
    if f.get("name") and f["name"] not in text:
        out.append(f'it does not call the company "{f["name"]}"')
    if "D" in lines and f"{f['lately']} compared with its past year" not in ss[-1]:
        out.append(f'its last sentence is not line D: "{lines["D"]}"')
    for i in restatements(text, f):
        out.append(f"sentence {i} restates an earlier sentence: it states no fact the earlier sentences had not")
    out += band_contradictions(text, f)
    return list(dict.fromkeys(out))


async def write_read(f: dict) -> dict:
    """{result: passed|failed|no_move, content, problems, model}. No model call; the read is checked like any other and never
    served when a check fails. Writes nothing."""
    out = {"result": "failed", "content": None, "problems": [], "model": READ_MODEL}
    if "A" not in fact_lines(f):             # no expected move: the read would have nothing true to lead with (CMS, 2026-10-26)
        out.update(result="no_move", problems=["no expected move in the page's facts"])
        return out
    text = compose_read(f)
    problems = read_problems(text, f)
    if problems:
        out["problems"] = problems
        return out
    out.update(result="passed", content=text)
    return out
