"""Ivy's one sentence beside each Discover row (behind DISCOVER_NEWS_ENABLED): in plain English, why the stock moved.

Her inputs are the stock's printed change and every stored story naming it (in its headline or summary) since the close before the
priced session, roundups and stories the page will not show included, each with its headline and summary. Nothing else.

She writes with Ask Ivy's model and pipeline (services/ask_ivy: Sonnet writes, a deterministic check, one rewrite with the check's
reasons, then the Opus verifier with her inputs as its only evidence). The check (check_sentence) rejects a sentence that
  - runs past MAX_WORDS words or is more than one sentence;
  - advises, predicts or gives an opinion (buy, sell, should, will, could, may, likely, undervalued, ...);
  - states a number (a dollar figure, a percent, any figure) that appears in none of her stories;
  - names a company, person or other proper noun that appears in none of her stories;
  - states a percent move for the stock that differs from the printed change at one decimal.
The verifier then marks the sentence supported only when every event in it is in her stories. A sentence that fails twice is not
shown: the row falls back to the headline display and the failure is stored with its reasons. When no stored story names the stock,
or she finds none that explains the move, she says exactly NO_NEWS.

Each sentence is stored (ivy_move_notes) with its sources, the check result, the cost and when it was written, keyed by the stock and
a fingerprint of the stories she read, so it is written again only when those stories change.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from app.services.headline_guard import _CLAUSE, CUE_SIGN, clauses_about, stated_move
from app.services.news import NEW_YORK, name_forms, names_company

NO_NEWS = "No reported news explains this move."
MAX_WORDS = 25
MAX_INPUT_STORIES = 30          # newest first; a stock with more stories than this is read from its newest
FALLBACK_WARN_SHARE = 0.2       # validate warns when more than this share of a run's rows fall back to the headline display
RUN_KEY = "ivy_moves_last_run"  # system_metadata: the latest run's counts, for validate
STEP_LABEL = "Ivy's Discover sentences"

ADVICE = re.compile(
    # buy and sell as advice ("a buy", "time to sell", "buy the stock", "buy now"), not a company's purchase ("agreed to buy spectrum")
    r"\b(?:a|strong|time\s+to|good\s+time\s+to)\s+(?:buy|sell)\b(?!-?\s?offs?\b)|\b(?:buy|sell)\s+(?:the\s+(?:stock|shares|dip)|shares|now|signal|rating)\b|"
    r"\b(?:buy|sell)(?=\s*(?:[.,;!]|$))|\bshould\b|\brecommend\w*|\bopportunit\w*|\bbargain\b|"
    r"\b(?:under|over)valued\b|\bcheap\b|\bexpensive\b|\battractive\b|\bbullish\b|\bbearish\b|\bi\s+think\b|\bwe\s+think\b|\bbelieve\b|"
    r"\b(?:up|down)side\b|\bcramer\b|\bwill\b|\bwould\b|\bcould\b|\bmay\b|\bmight\b|\blikely\b|(?<!than\s)(?<!than-)\bexpect(?:s|ed|ing)?\b|\bpoised\b|\bforecasts?\b|\bpredict\w*|\bgoing\s+to\b",
    re.I)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
PROPER = re.compile(r"(?<![A-Za-z0-9$])[A-Z][A-Za-z0-9&.'’-]*")
RATING_CHANGE = re.compile(r"\b(?:upgrade|downgrade)[sd]?\b|\b(?:buy|sell)\s+rating\b", re.I)   # reporting an analyst's action, not advice
COMMON_CAPS = {"the", "a", "an", "its", "it", "shares", "share", "stock", "stocks", "after", "on", "in", "as", "following", "amid", "with",
               "investors", "investor", "analysts", "analyst", "traders", "today", "this", "that", "his", "her", "their", "and", "of", "for", "to", "from", "by", "s&p",
               "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april",
               "may", "june", "july", "august", "september", "october", "november", "december", "jan", "feb", "mar", "apr", "jun",
               "jul", "aug", "sep", "sept", "oct", "nov", "dec", "ceo", "cfo", "q1", "q2", "q3", "q4", "u.s.", "us", "wall", "street"}


def story_text(story: dict) -> str:
    return f"{story.get('headline') or ''} {story.get('summary') or ''}"


def input_stories(stories: list[dict], symbol: str, name: str | None, since: datetime) -> list[dict]:
    """Pure: every story naming the stock (in its headline or its summary) published since `since`, newest first, at most
    MAX_INPUT_STORIES. Roundups and stories the page will not show are included: they can still explain a move."""
    named = [s for s in stories if s["published_at"] >= since and names_company(story_text(s), symbol, name)]
    return sorted(named, key=lambda s: s["published_at"], reverse=True)[:MAX_INPUT_STORIES]


def fingerprint(symbol: str, inputs: list[dict]) -> str:
    """Pure: the stories she read, as one key: a new, changed or dropped story writes the sentence again."""
    body = "\n".join(sorted(f"{s['url']}|{s.get('headline')}|{s.get('summary') or ''}" for s in inputs))
    return hashlib.sha256(f"{symbol}\n{body}".encode()).hexdigest()[:40]


def _when(dt: datetime) -> str:
    return dt.astimezone(NEW_YORK).strftime("%a %b %-d, %-I:%M %p ET")


def build_prompt(symbol: str, name: str | None, move_pct: float, inputs: list[dict]) -> str:
    stories = "\n\n".join(f"[{i}] {s['headline']} ({s.get('source') or 'unknown source'}, {_when(s['published_at'])})"
                          + (f"\n    Summary: {s['summary']}" if s.get("summary") else "") for i, s in enumerate(inputs, 1))
    return f"""You are Ivy, the analyst on a stock research site. Write one sentence, at most {MAX_WORDS} words, in plain English, saying why
{name or symbol} ({symbol}) moved today. The page prints its change beside your sentence: {move_pct:+.2f}%.

STORIES (your only source; use no outside knowledge):
{stories}

RULES
- Use only facts from the stories. Every company, person, dollar figure, percent and event you mention must appear in a story.
- Do not restate the stock's own percent change; it is printed beside your sentence. If you must, write it as {abs(move_pct):.1f}% exactly.
- Count the words: at most {MAX_WORDS}. Name one or two events, not every detail.
- Explain; never advise. No predictions (no will, could, may, might, likely, expected), no buy or sell language, no opinions.
- Say what happened, not what it means for investors. Name the event that moved the stock.
- A sentence that only restates that the stock moved, or compares it with the market, explains nothing: answer NONE instead.
- If no story explains this move, the sentence is NONE.

Return one JSON object and nothing before or after it: {{"sentence": "...", "sources": [the numbers of the stories that informed it, most informative first]}}"""


def last_json(content: str) -> dict | None:
    """Pure: the last JSON object in the text that parses (a model that reconsiders after its first answer ends on its final one)."""
    dec, found, i = json.JSONDecoder(), None, 0
    while (i := content.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(content, i)
            if isinstance(obj, dict):
                found = obj
            i = end
        except ValueError:
            i += 1
    return found


def parse_output(content: str) -> tuple[str, list[int]]:
    """Pure: (sentence, source numbers) from the model's JSON; ("", []) when it cannot be read."""
    data = last_json(content)
    if data is None:
        return "", []
    sentence = " ".join(str(data.get("sentence") or "").split())
    sources = [int(x) for x in data.get("sources") or [] if str(x).isdigit()]
    return sentence, sources


def _numbers(text_: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text_)}


def check_sentence(sentence: str, inputs: list[dict], symbol: str, name: str | None, move_pct: float | None) -> list[str]:
    """Pure: every reason the sentence cannot show beside a stock whose printed change is `move_pct`. Empty when it passes."""
    problems: list[str] = []
    s = sentence.strip()
    if not s:
        return ["no sentence"]
    words = s.split()
    if len(words) > MAX_WORDS:
        problems.append(f"{len(words)} words, more than {MAX_WORDS}")
    if len(re.findall(r"[.!?](?:\s+[A-Z]|$)", s)) > 1:
        problems.append("more than one sentence")
    advice = sorted({m.group(0).lower() for m in ADVICE.finditer(s)
                     if not (RATING_CHANGE.search(s) and re.search(r"\b(?:buy|sell)\b", m.group(0), re.I))})
    if advice:
        problems.append(f"advice, prediction or opinion wording: {', '.join(advice)}")
    corpus = " ".join(story_text(x) for x in inputs)
    known = _numbers(corpus)
    for n in sorted(_numbers(s)):
        if n not in known:
            problems.append(f"the figure {n} appears in none of her stories")
    forms = name_forms(symbol, name)
    allowed = {w.lower() for f in forms for w in f.split()} | {symbol.lower()}
    low = corpus.lower()
    for m in PROPER.finditer(s):
        tok = re.sub(r"(?:'s|’s|['’.,;:])+$", "", m.group(0))
        key = tok.lower()
        if not tok or key in COMMON_CAPS or key in allowed or key.isdigit():
            continue
        found = lambda k: bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])", low))
        parts = [x for x in re.split(r"-", tok) if x[:1].isupper()]           # "AI-related": its capitalized parts
        if not found(key) and not (len(parts) < len(tok.split("-")) and parts and all(found(x.lower()) for x in parts)):
            problems.append(f"the name {tok} appears in none of her stories")
    pct = stock_percent_problem(s, symbol, name, move_pct)
    if pct:
        problems.append(pct)
    return problems


# words that restate a move without naming what moved it: a sentence made only of these (and the stock's name) explains nothing
FILLER = {"the", "a", "an", "and", "as", "on", "in", "of", "its", "it", "with", "while", "amid", "among", "after", "despite", "even", "was",
          "were", "is", "market", "markets", "broader", "broad", "wider", "overall", "gains", "gained", "day", "today", "session", "notable",
          "decliner", "decliners", "gainer", "gainers", "standing", "out", "stock", "stocks", "share", "shares", "investor", "investors",
          "index", "sharply", "trading", "traded", "other", "peers", "sector", "attention", "interest", "s&p", "500", "move", "moved", "big",
          "biggest", "one", "this", "that", "friday", "monday", "tuesday", "wednesday", "thursday", "slightly", "steeply", "solidly"}


def explains_nothing(sentence: str, symbol: str, name: str | None) -> bool:
    """Pure: the sentence only restates that the stock moved ("HP stock dropped despite broader market gains"): no event in it."""
    own = {w.lower() for f in name_forms(symbol, name) for w in re.findall(r"[A-Za-z0-9&]+", f)} | {symbol.lower()}
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9&]+", sentence)} - own - {"s"}
    return all(w in FILLER or w in CUE_SIGN for w in words)


def stock_percent_problem(sentence: str, symbol: str, name: str | None, move_pct: float | None) -> str | None:
    """Pure: a stated percent move counts as the stock's unless its clause names another company (any proper noun besides the
    stock's own name); the stock's must match the printed change at one decimal and in sign."""
    if move_pct is None:
        return None
    own = {w.lower() for f in name_forms(symbol, name) for w in f.split()} | {symbol.lower()}
    for clause in [c for c in _CLAUSE.split(sentence) if c and c.strip()]:
        v = stated_move(clause)
        if v is None:
            continue
        others = [t for t in re.findall(r"(?<![A-Za-z0-9$])[A-Z][A-Za-z0-9&.'’-]*", clause)
                  if re.sub(r"(?:'s|’s|['’.,;:])+$", "", t).lower() not in own | COMMON_CAPS]
        if others and not any(o.lower() in own for o in others):
            continue                                              # another company's move
        if round(abs(v), 1) != round(abs(move_pct), 1) or (v > 0) != (move_pct > 0):
            return f"it states {v:+g}% for the stock against the printed {move_pct:+.2f}%"
    return None


def build_verification_prompt(symbol: str, name: str | None, sentence: str, inputs: list[dict]) -> str:
    stories = "\n".join(f"- {s['headline']}" + (f" | {s['summary']}" if s.get("summary") else "") for s in inputs)
    return f"""You are a rigorous fact-checker. Check the sentence below about {name or symbol} ({symbol}) against these stories ONLY.

STORIES:
{stories}

SENTENCE:
{sentence}

"supported": every company, person, figure and event in the sentence, and the link it draws between the event and the stock's move,
is stated in the stories. "unsupported": anything in it is not in the stories (outside knowledge, an inference the stories do not
make). "contradicted": it conflicts with a story. Bias toward "unsupported" when in doubt. Use no outside knowledge.

Return JSON only: {{"status": "supported|unsupported|contradicted", "evidence": "..."}}"""


def parse_verdict(content: str) -> tuple[str, str]:
    data = last_json(content)
    return (str(data.get("status") or ""), str(data.get("evidence") or "")) if data else ("", "")


def source_rows(inputs: list[dict], numbers: list[int]) -> list[dict]:
    """Pure: the stories she named, in her order, as stored receipts (lead first)."""
    out, seen = [], set()
    for n in numbers:
        if 1 <= n <= len(inputs) and n not in seen:
            seen.add(n)
            s = inputs[n - 1]
            out.append({"url": s["url"], "headline": s["headline"], "source": s.get("source"), "published_at": s["published_at"].isoformat()})
    return out


async def explain(symbol: str, name: str | None, move_pct: float, inputs: list[dict], *, client=None) -> dict:
    """Write, check and verify one sentence: {result, sentence, sources, problems, attempts, model, input_tokens, output_tokens,
    cost_usd}. result is "passed", "no_news" or "fallback". Writes nothing to the database."""
    from app.services.research_cost import estimate_cost_usd
    out = {"result": "no_news", "sentence": NO_NEWS, "sources": [], "problems": [], "attempts": 0, "model": None,
           "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    if not inputs:
        return out
    if client is None:
        from app.services.anthropic_client import AnthropicClient
        client = AnthropicClient()

    def charge(gen: dict) -> None:
        out["input_tokens"] += gen["input_tokens"]; out["output_tokens"] += gen["output_tokens"]
        out["cost_usd"] += estimate_cost_usd(gen["model_used"], gen["input_tokens"], gen["output_tokens"]) or 0.0

    prompt = build_prompt(symbol, name, move_pct, inputs)
    reasons: list[str] = []
    for attempt in (1, 2):
        out["attempts"] = attempt
        ask = prompt if attempt == 1 else (prompt + "\n\nYour previous sentence was rejected for these reasons: " + "; ".join(reasons)
                                           + f". Rewrite it so none applies, in at most {MAX_WORDS} words, or answer NONE if no story explains the move.")
        gen = await client.generate_answer(ask, max_tokens=300)
        out["model"] = gen["model_used"]
        charge(gen)
        sentence, numbers = parse_output(gen["content"])
        if sentence.upper().rstrip(".") == "NONE" or (sentence and explains_nothing(sentence, symbol, name)):
            out.update(result="no_news", sentence=NO_NEWS, sources=[])
            return out
        reasons = check_sentence(sentence, inputs, symbol, name, move_pct)
        sources = source_rows(inputs, numbers)
        if not sources:
            reasons.append("it names none of her stories as a source")
        if not reasons:
            ver = await client.verify_research_note(build_verification_prompt(symbol, name, sentence, inputs))
            charge(ver)
            status, evidence = parse_verdict(ver["content"])
            if status == "supported":
                out.update(result="passed", sentence=sentence, sources=sources)
                return out
            reasons = [f"the verifier marked it {status or 'unreadable'}: {evidence}"[:300]]
        out["problems"].append({"attempt": attempt, "sentence": sentence, "reasons": reasons})
    out.update(result="fallback", sentence=None, sources=[])
    return out


def lead_index(sources: list[dict], move_pct: float | None, symbol: str, name: str | None) -> int | None:
    """Pure: which of her sources to link under the sentence: the first whose headline the headline guard lets beside the printed
    change (a source saying "Rallies 6%" never sits beside a printed +4.30%); None when none does."""
    from app.services.headline_guard import check
    forms = name_forms(symbol, name)
    return next((i for i, s in enumerate(sources) if check(s["headline"], move_pct, forms).reason is None), None)


def display_ok(note: dict, move_pct: float | None, symbol: str, name: str | None) -> bool:
    """Pure: a stored sentence may show beside the change printed now: passed, and any percent it states for the stock still
    matches the printed change at one decimal (the printed change can move after the sentence was written)."""
    if note.get("result") == "no_news":
        return True
    if note.get("result") != "passed" or not note.get("sentence"):
        return False
    return stock_percent_problem(note["sentence"], symbol, name, move_pct) is None
