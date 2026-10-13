"""Ask Ivy: the free-text question box under the question strip (flag ASK_IVY_ENABLED, off in production).

Ivy answers the decision behind the question the way an analyst explains it to a beginner, from this stock's stored facts, and
never dead-ends: a question the facts cannot reach gets one plain sentence saying what she does not track, and only a question
with nothing to do with this stock gets a refusal that names what she can answer. The model classifies each question (one small
call, services/anthropic_client.classify_question: timing, direction, quality, options planning, another covered question, not
covered, off topic); a decision question is answered facts first and closes with exactly one line, CLOSING_LINE, appended by code.
Answers stay under WORD_CAP words with no unexplained terms, every figure that is not today's carries its date through its fact's
phrase, and words that imply a call (FORBIDDEN_PHRASES, VALUATION_VERDICTS) or a beat or miss figure never pass. The model (Sonnet)
sees the fact pack, names and values, so it can reason over them, but it may not type a number: its output must refer
to every quantity by a {fact:id} placeholder. The output check (check_output) rejects any digit, currency sign or percent
outside a placeholder, number words (one through twenty, twice, double, triple, half, a quarter as a fraction, dozen),
an unknown placeholder, more than three sentences, and recommendation language. Comparisons ("more than usual", "below
its 52-week high", "elevated") arrive precomputed as word-valued facts, and verify_comparisons checks every comparison
word the model used against them. Values are then substituted from the fact pack, each carrying its receipt, and the
rendered answer goes to the verifier (Opus, the research-note verifier's model) with the fact pack as its only evidence:
a sentence it marks unsupported or contradicted is dropped before display.

Every question is logged (ask_log) with its normalized form, whether the facts covered it, the verdict and the cost.
Repeated questions are served from the log while the fact pack is unchanged (the cache key holds a fingerprint of every
fact's value and date). Visitors are limited per IP and per IP and stock (ASK_POLICY, ASK_TICKER_POLICY) and the box
pauses for the day once the site's estimated spend reaches settings.ask_ivy_daily_cap_usd.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import briefing as B
from app.services.draft_limiter import LimitPolicy
from app.services.move_comparison import compare_moves
from app.services.research_cost import estimate_cost_usd
from app.services.system_metadata_service import get_value, set_value

MAX_SENTENCES = 6
WORD_CAP = 90                               # an answer longer than this is rewritten once, then cut at a sentence end
MAX_QUESTION_CHARS = 300
# A question never hangs (2026-10-13: a test run stalled for hours inside a model call, since the SDK's default allows ten minutes
# and two retries per call). Every model call is bounded, each stage has a deadline, and a stage that runs out returns timeout_answer.
MODEL_CALL_SECONDS = 20                    # one attempt of one model call (the SDK's own timeout), one retry
PACK_SECONDS = 10                          # the fact pack: database reads only
CLASSIFY_SECONDS = 8                       # the classifier, one small call
ANSWER_SECONDS = 45                        # the whole answer: the draft, at most one rewrite and the verification
CACHE_VERSION = 2                           # 2 (2026-10-12): the analyst's voice; every answer cached before it is never served again
KINDS = ("timing", "direction", "quality", "options_planning", "extraction", "covered_other", "not_covered", "off_topic")
DECISION_KINDS = ("timing", "direction", "quality", "options_planning")     # a buy, sell or trade decision: facts first, then CLOSING_LINE
CLOSING_LINE = "Ivy doesn't make buy or sell calls."
BEAT_FACTS = {"beats", "beats_followed_by_a_fall", "share", "last_report_outcome"}   # beat or miss figures never enter a decision answer
# Intrinio's terms (2026-10-12): a figure may be cited inside an explanation; a raw series or table (daily closes, a chain, OHLC bars,
# strike-by-strike bids, a CSV) never leaves through Ivy. FIGURE_CAP is the most distinct prices, moves or option quotes one answer
# may carry: the test set's served answers carried at most six (most three or four), and a ninety-word answer with a why clause
# on every figure has no room for more, while the smallest series anyone asks for (a week of closes, a handful of strikes with
# bids) runs past it or trips the series check below.
FIGURE_CAP = 8
EXTRACTION_LINE = "Ivy doesn't list price series, option chains or exports; the chart holds the price history and the Options section holds the strikes."
PRICE_FIGURE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|[+\-−±]?\d+(?:\.\d+)?\s?%")
_DATE = r"(?:[A-Z][a-z]{2,8}\.? \d{1,2}(?:, \d{4})?|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
DATED_RUN = re.compile(r"(?:" + _DATE + r"[:,]?\s*[+\-−±]?\$?\d[\d,]*(?:\.\d+)?%?\s*[,;]\s*){2,}" + _DATE)     # three or more "date price" pairs in a row
FIGURE_RUN = re.compile(r"(?:[+\-−±]?\$?\d[\d,]*(?:\.\d+)?%?\s*,\s+){3,}[+\-−±]?\$?\d")                       # four or more bare figures in a row
PLACEHOLDER_RUN = re.compile(r"(?:\{fact:[a-z0-9_]+\}\s*[,;|]\s*){3,}\{fact:")                                    # the same run before rendering
TABLE_MARK = re.compile(r"\||\t")
ROW_START = re.compile(r"^\s*(?:\{fact:[a-z0-9_]+\}|[A-Z][a-z]{2} \d{1,2}|[+\-−±]?\$?\d)[^A-Za-z\n]*[,|\t]", re.M)   # a line that is a row of figures
SPEND_KEY = "ask_ivy_spend"                 # system_metadata "{SPEND_KEY}:{YYYY-MM-DD}" holds the day's estimated spend in USD
RV_ELEVATED_RANK = 80                       # 20-day realized volatility at or above this percentile of its own year is "elevated"
RV_QUIET_RANK = 20                          # at or below this percentile, "quiet"

ASK_POLICY = LimitPolicy(prefix="ask_ivy", per_ip_hour=10, per_ip_day=30, global_day=1500, admin_bypasses_global=False,
                         per_ip_hour_message="Ivy answers up to {n} questions an hour per visitor; try again after {at}.",
                         per_ip_day_message="Ivy answers up to {n} questions a day per visitor; try again after {at}.",
                         global_message="Ivy has answered today's site-wide limit of {n} questions; try again tomorrow.", noun="Asking Ivy")
ASK_TICKER_POLICY = LimitPolicy(prefix="ask_ivy_ticker", per_ip_day=10, global_day=10**9, admin_bypasses_global=False,
                                per_ip_day_message="Ivy answers up to {n} questions a day per visitor about one stock; try again after {at}.", noun="Asking Ivy")

PLACEHOLDER = re.compile(r"\{fact:([a-z0-9_]+)\}")
_NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
                 "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "twice", "double", "triple", "dozen")
NUMBER_WORD = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.I)
HALF = re.compile(r"(?<!first )(?<!second )\bhalf\b(?!-year)", re.I)                 # "half" as a fraction; "first half" and "half-year" are periods
QUARTER_FRACTION = re.compile(r"\b(?:a|one|three)\s+quarters?\b|\bquarters?\s+of\b", re.I)   # "a quarter of"; "third quarter" is a period
FORBIDDEN_CHARS = re.compile(r"[0-9$%€£]")
WINDOW_NAMES = ("52-week", "20-day", "1-day", "3-day", "5-day", "five-year", "S&P 500")        # names of windows and an index, as the strip's own copy uses them; never a quantity
_WINDOW = re.compile("|".join(re.escape(w) for w in WINDOW_NAMES))
RECOMMENDATION = re.compile(r"\b(you should (?:buy|sell|hold)|i(?:'d| would) (?:buy|sell)|i recommend|buy now|sell now|(?:a |is a )?(?:good|bad|great) (?:buy|time to buy|time to sell)|worth buying|worth selling)\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
STOPWORDS = {"the", "is", "it", "its", "a", "an", "of", "to", "in", "on", "for", "and", "or", "right", "now", "currently", "today", "does", "do", "did",
             "has", "have", "was", "were", "be", "been", "this", "that", "at", "about", "with", "what", "how", "why", "will", "would", "should", "i", "we", "you", "my"}
SYNONYMS = {"fall": ("drop", "dropped", "drops", "fell", "falls", "falling", "decline", "declined", "declines", "down", "lower", "plunge", "plunged", "tank", "tanked"),
            "rise": ("rose", "rises", "rising", "jump", "jumped", "jumps", "up", "higher", "gain", "gained", "gains", "climb", "climbed", "rally", "rallied", "surge", "surged"),
            "expensive": ("pricey", "rich", "overvalued", "overpriced", "costly", "dear"), "cheap": ("undervalued", "underpriced", "bargain", "inexpensive"),
            "stock": ("shares", "share", "equity", "price", "stockprice"), "buy": ("purchase", "bought", "buying", "invest", "investing"),
            "sell": ("sold", "selling", "dump", "exit"), "earnings": ("results", "report", "quarter", "eps", "profits"), "move": ("moved", "moves", "moving", "react", "reacted", "reaction"),
            "dividend": ("payout", "distribution", "yield"), "volatile": ("volatility", "choppy", "swingy", "wild"), "usual": ("normal", "typical", "typically", "usually", "average")}
_SYN_INDEX = {w: k for k, ws in SYNONYMS.items() for w in ws}

COMPARISONS: list[tuple[re.Pattern, dict[str, str]]] = [
    # (phrase the model may use, {word fact: the value that phrase asserts}); the phrase passes when any listed fact holds its value
    (re.compile(r"\bmore than usual\b|\b(?:above|bigger than|larger than) (?:its |the )?(?:usual|typical)\b|\b(?:bigger|larger) than usual\b", re.I),
     {"implied_vs_typical": "more than usual", "last_move_vs_typical": "more than usual"}),
    (re.compile(r"\bless than usual\b|\b(?:below|smaller than) (?:its |the )?(?:usual|typical)\b|\bsmaller than usual\b", re.I),
     {"implied_vs_typical": "less than usual", "last_move_vs_typical": "less than usual"}),
    (re.compile(r"\babout (?:as |the same as )?usual\b|\bin line with (?:its |the )?(?:usual|typical)\b|\babout what it usually\b|\bclose to (?:its |the )?(?:usual|typical)\b", re.I),
     {"implied_vs_typical": "about usual", "last_move_vs_typical": "about usual"}),
    (re.compile(r"\bbelow (?:its|the|a) (?:52-week|year|yearly|one-year|twelve-month) high\b|\boff (?:its|the) high\b|\bunder its (?:52-week|year) high\b", re.I), {"price_vs_52_week_high": "below"}),
    (re.compile(r"\b(?:at|near) (?:its|a|the) (?:52-week|year|yearly|one-year|twelve-month|new) high\b", re.I), {"price_vs_52_week_high": "near"}),
    (re.compile(r"\belevated\b|\bmore volatile than usual\b|\bmore active than usual\b|\bunusually volatile\b", re.I), {"volatility_vs_year": "elevated"}),
    (re.compile(r"\bquiet(?:er)?\b|\bless volatile than usual\b|\bcalmer than usual\b|\bunusually calm\b", re.I), {"volatility_vs_year": "quiet"}),
    (re.compile(r"\bvolatility (?:is|looks|sits) (?:about )?(?:normal|typical|ordinary)\b|\bin its normal range\b|\bnot unusually volatile\b", re.I), {"volatility_vs_year": "normal"}),
    (re.compile(r"\bbeat\b[^.]{0,40}\bestimates?\b|\bbeat the street\b|\btopped (?:the )?estimates?\b|\bexceeded (?:the )?estimates?\b|\bwas a beat\b", re.I), {"last_report_outcome": "beat"}),
    (re.compile(r"\bmissed\b[^.]{0,40}\bestimates?\b|\bfell short of (?:the )?estimates?\b|\bwas a miss\b", re.I), {"last_report_outcome": "miss"}),
    (re.compile(r"\bmet\b[^.]{0,40}\bestimates?\b|\bmatched (?:the )?estimates?\b|\bin line with (?:the )?estimates?\b", re.I), {"last_report_outcome": "meet"}),
    (re.compile(r"\bafter the (?:close|bell|market closes?)\b", re.I), {"next_report_timing": "after the close", "last_report_timing": "after the close"}),
    (re.compile(r"\bbefore the (?:open|bell|market opens?)\b", re.I), {"next_report_timing": "before the open", "last_report_timing": "before the open"}),
    (re.compile(r"(?<!not )(?<!un)\bconfirmed\b", re.I), {"next_report_status": "confirmed", "dividend_status": "declared"}),
    (re.compile(r"\b(?:an )?estimated(?: date| report date)?\b|\bnot (?:yet )?confirmed\b|\bunconfirmed\b|\bnot (?:yet )?declared\b", re.I), {"next_report_status": "estimated", "dividend_status": "estimated"}),
    (re.compile(r"(?<!not )(?<!yet )\bdeclared\b", re.I), {"dividend_status": "declared"}),
    (re.compile(r"\babove its (?:own )?(?:five-year|5-year|historical|long-run) (?:median|norm|average)\b|\bricher than its (?:own )?history\b|\bhigher than its (?:own )?(?:five-year )?median\b", re.I), {"pe_vs_history": "above"}),
    (re.compile(r"\bbelow its (?:own )?(?:five-year|5-year|historical|long-run) (?:median|norm|average)\b|\blower than its (?:own )?(?:five-year )?median\b", re.I), {"pe_vs_history": "below"}),
    (re.compile(r"\babove (?:its |the )?(?:sector|peer|peers'|industry) median\b|\babove its peers\b|\bhigher than its (?:sector|peers)\b", re.I), {"pe_vs_sector": "above"}),
    (re.compile(r"\bbelow (?:its |the )?(?:sector|peer|peers'|industry) median\b|\bbelow its peers\b|\blower than its (?:sector|peers)\b", re.I), {"pe_vs_sector": "below"}),
    (re.compile(r"\bin line with its (?:own )?(?:five-year|5-year|historical|long-run) (?:median|norm|average)\b|\b(?:at|matches|equal to) its (?:own )?(?:five-year|5-year) median\b", re.I), {"pe_vs_history": "in line with"}),
    (re.compile(r"\bin line with (?:its |the )?(?:sector|peer|peers'|industry) median\b|\bin line with its peers\b|\b(?:at|matches|equal to) (?:its |the )?(?:sector|peer) median\b", re.I), {"pe_vs_sector": "in line with"}),
]
VALUATION_VERDICTS = re.compile(r"\b(?:cheap|expensive|undervalued|overvalued|pricey|a bargain|overpriced|underpriced)\b", re.I)   # a ratio is never a verdict
# words that imply a call, or talk about her own sources: never shown (Sam's voice rules, 2026-10-12)
FORBIDDEN_PHRASES = re.compile(r"\b(?:bargain|good entry|the facts show|the data indicates?|the data shows?|this page|the facts here|the stored facts|stored data|"
                               r"the facts (?:do not|don't) cover|my sources|the page's|according to the (?:facts|data)|"
                               r"the chart|chart above|options section|scroll back|lives in|on this page|of this page)\b", re.I)   # the pointer to the chart is the code's line, never the model's
JARGON = re.compile(r"\b(?:IV|RV|ATM)\b")                              # bare initials, case-sensitive; "implied move" and "typical move" are the words
JARGON_WORDS = re.compile(r"\bstraddles?\b", re.I)
_BEAT = r"(?:beat|beats|miss|missed|misses)"
_ESTIMATE = r"(?:estimates?|expectations?|consensus|the street|eps|forecasts?|guidance)"
BEAT_WORDS = re.compile(r"\b" + _BEAT + r"\b[^.]{0,40}\b" + _ESTIMATE + r"\b|\b" + _ESTIMATE + r"\b[^.]{0,40}\b" + _BEAT + r"\b"
                        r"|\b(?:a|an|the|its last|last|an earnings|its latest) (?:beat|miss)\b|\bbeats? and (?:falls?|fell)\b", re.I)   # an earnings beat or miss; "misses the move" is prose


# ── the question's kind: the model decides, no keyword list ──────────────────────────────────────────────────────

CLASSIFIER_PROMPT = """Classify a visitor's question typed on the stock page of {name} ({symbol}). Return JSON only: {{"kind": "<one of the kinds>"}}.

Kinds:
- timing: whether now is a good time to buy or sell, whether to get in or out before or after an event ("is now a good time to buy", "should I sell", "should I get in before earnings").
- direction: what the stock will do after an event or in general ("will it go up after earnings", "will it rally", "is it going to drop").
- quality: whether it is a good stock, a good company, worth it, risky, expensive or cheap as an investment.
- options_planning: expirations, strikes, timing around events, what the options are pricing, implied moves.
- extraction: asks for a raw series, table or export rather than an explanation: a list of daily closes, price history, a full options chain, every strike and bid, OHLC bars, a CSV or download.
- covered_other: any other question about this company or its stock (what it does, when it reports, how it has moved, recent drops, dividends, valuation ratios, volatility).
- not_covered: about this company but about something the page does not hold: news, product launches, lawsuits, management, guidance details, competitors.
- off_topic: not about this company or its stock at all (sports, weather, another company, chit-chat, questions about Ivy herself).

QUESTION: {question}"""


def build_classifier_prompt(question: str, symbol: str, name: str | None) -> str:
    return CLASSIFIER_PROMPT.format(name=name or symbol, symbol=symbol, question=" ".join(question.split())[:MAX_QUESTION_CHARS])


def parse_kind(content: str) -> str:
    """Pure: the kind in the classifier's JSON; anything unreadable is covered_other (the answer path still checks every fact)."""
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        kind = str(json.loads(m.group(0)).get("kind", "")).strip().lower() if m else ""
    except ValueError:
        kind = ""
    return kind if kind in KINDS else "covered_other"


def ask_client():
    """The model client for Ask Ivy: each attempt bounded at MODEL_CALL_SECONDS, one retry."""
    from app.services.anthropic_client import AnthropicClient
    return AnthropicClient(timeout=MODEL_CALL_SECONDS, max_retries=1)


async def classify_question(client, question: str, symbol: str, name: str | None) -> dict:
    """The model's kind for the question: {kind, model, input_tokens, output_tokens, cost}; raises asyncio.TimeoutError past
    CLASSIFY_SECONDS (the caller answers as covered_other)."""
    out = await asyncio.wait_for(client.classify_question(build_classifier_prompt(question, symbol, name)), CLASSIFY_SECONDS)
    return {"kind": parse_kind(out["content"]), "model": out["model_used"], "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
            "cost": estimate_cost_usd(out["model_used"], out["input_tokens"], out["output_tokens"]) or 0.0}


def can_answer_clause(pack: dict) -> str:
    """What Ivy can answer about this stock, from what the pack holds."""
    ids = {f["id"] for f in pack.get("facts", [])}
    parts = []
    if "next_earnings_date" in ids or "next_report_day" in ids:
        parts.append("its next report")
    if "typical_move" in ids or "reports_up" in ids:
        parts.append("how it has moved after past reports")
    if any(i.startswith("implied_move") for i in ids):
        parts.append("what the options are pricing")
    if "quote" in ids or "last_close" in ids:
        parts.append("where its price sits in its range")
    if "description" in ids:
        parts.append("what the company does")
    if not parts:
        return "its stored figures"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def refusal_answer(pack: dict, question: str) -> dict:
    """The one allowed refusal: nothing relevant to this stock, and what she can answer about it."""
    text_ = f"That isn't about {pack['name']}; Ivy can answer about {can_answer_clause(pack)}."
    return {"key": "ask", "question": question, "data": text_, "idea": "", "inputs": [], "as_of": None, "as_of_kind": "observed", "rule": RULE}


def extraction_decline(pack: dict, question: str) -> dict:
    """The helpful decline when a series was asked for and no explanation passed: where the series lives, and what she can answer."""
    return {"key": "ask", "question": question, "data": f"{EXTRACTION_LINE} She can answer about {can_answer_clause(pack)}.", "idea": "", "inputs": [],
            "as_of": None, "as_of_kind": "observed", "rule": RULE}


def distinct_figures(rendered: str) -> int:
    """Pure: how many distinct prices, moves or option quotes (dollar amounts and percentages) the text carries."""
    return len({m.group(0).lstrip("+-−±$ ").replace(" ", "") for m in PRICE_FIGURE.finditer(rendered)})


def series_problems(draft: str, rendered: str, raw: str = "") -> list[str]:
    """Pure: every reason the text is a series or table rather than an explanation (Intrinio's terms): a table or row mark, a run
    of dated prices or bare figures, or more than FIGURE_CAP distinct figures."""
    problems: list[str] = []
    if TABLE_MARK.search(draft) or TABLE_MARK.search(rendered) or TABLE_MARK.search(raw) or len(ROW_START.findall(raw)) >= 2:
        problems.append("a table or rows of figures")
    if PLACEHOLDER_RUN.search(draft) or DATED_RUN.search(rendered) or FIGURE_RUN.search(rendered):
        problems.append("a run of listed figures")
    n = distinct_figures(rendered)
    if n > FIGURE_CAP:
        problems.append(f"more than {FIGURE_CAP} figures ({n})")
    return problems


def fixed_answer(kind: str, pack: dict, question: str) -> dict:
    """Off topic is the refusal; anything else is the not-covered sentence."""
    return refusal_answer(pack, question) if kind == "off_topic" else not_covered_answer(pack, question)


def repeated_phrase(sentence: str, words: int = 4) -> str | None:
    """Pure: a run of `words` words that appears twice in one sentence ("were followed by a fall … were followed by a fall"), else None."""
    toks = re.findall(r"[a-z0-9]+", sentence.lower())       # words only: punctuation never makes "report." differ from "report"
    seen: dict[tuple, int] = {}
    for i in range(len(toks) - words + 1):
        gram = tuple(toks[i:i + words])
        if gram in seen and i >= seen[gram] + words - 1:
            return " ".join(gram)
        seen.setdefault(gram, i)
    return None


# ── fact pack ────────────────────────────────────────────────────────────────

# Sentence-ready phrasing per fact name: how the value reads inside a sentence. {value} is the quantity as the receipt shows it,
# so the frontend's tokenizer still finds it. Every phrase is a noun phrase (never a verb phrase, so the model's own verb cannot
# double it); a name absent here reads as its bare value. test_ask_ivy checks the no-verb rule over this table.
PHRASES: dict[str, str] = {
    "distance below 52-week high": "{value} below its 52-week high",
    "three-month change": "a {value} change over the past three months",
    "1-day move": "a {value} move",
    "median 1-day move after an upgrade": "a {value} median move",
    "three-month anchor close": "{value} three months ago",
    "quote time": "as of {value}",
    "last close": "a last close of {value}",
    "typical move": "{value} on a typical report",
    "typical move after a report": "{value} on a typical report",
    "typical daily move": "{value} on a typical day",
    "reports moving more": "{value} of its reports",             # with its denominator when the sample size is a fact: "15 of its last 20 reports"
    "reports in the sample": "its last {value} reports",
    "beats": "its last {value} beats",
    "beats followed by a fall": "{value} of its beats",           # "11 of its last 18 beats" when the beat count is a fact
    "share": "{value}",
    "20-day realized volatility": "{value} annualized",
    "sessions in the past year": "{value} trading sessions in the past year",
    "dividend per share": "{value} per share",
    "days away": "{value} days away",
    "implied move": "about {value} either way",
    "largest up move": "its largest gain, {value}",
    "largest down move": "its largest fall, {value}",
    "market cap": "a market value of about {value}",
    "shares outstanding": "{value} shares outstanding",
    "EPS actual": "{value} a share",
    "EPS estimate": "an estimate of {value} a share",
    "daily move": "a daily move of {value}",
    "upgrades in the last month": "{value} upgrades in the past month",
    "P/E": "{value} times its earnings of the last four reported quarters",
    "five-year median P/E": "{value}",
    "sessions below today's P/E": "{value} of its sessions over the past five years",   # with the session count when stored (DENOMINATORS)
    "sector median P/E": "{value}",
}
_WINDOW_VALUE = re.compile(r"close (?P<base>[A-Z][a-z]{2} \d{1,2}, \d{4}) to close (?P<after>[A-Z][a-z]{2} \d{1,2}, \d{4})")


def phrase_for(name: str, value: str) -> str:
    return PHRASES.get(name, "{value}").format(value=value)


# a count fact whose phrase carries another fact's value as its denominator: (numerator name, denominator name, phrase)
DENOMINATORS: list[tuple[str, str, str]] = [
    ("beats followed by a fall", "beats", "{value} of its last {denominator} beats"),
    ("reports moving more", "reports in the sample", "{value} of its last {denominator} reports"),
    ("beats followed by a fall", "reports in the sample", "{value} of its beats in its last {denominator} reports"),
    ("sessions below today's P/E", "sessions compared", "{value} of its {denominator} sessions over the past five years"),
]


def with_denominators(facts: list[dict]) -> list[dict]:
    """Pure: count facts read with their denominator when that fact is in the pack; the denominator fact's id is kept as a
    companion so its receipt renders too. The first matching pair per numerator wins."""
    by_name = {f["name"]: f for f in facts}
    done: set[str] = set()
    for num, den, template in DENOMINATORS:
        n, d = by_name.get(num), by_name.get(den)
        if n is None or d is None or num in done:
            continue
        n["phrase"] = template.format(value=n["value"], denominator=d["value"])
        n["companions"] = [d["id"]]
        d["hidden"] = True          # offered to the model only inside the numerator's phrase, so it cannot be placed twice; still rendered and receipted
        done.add(num)
    return facts

def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _fact(fid: str, name: str, value, as_of, source: str | None, kind: str = "number", phrase: str | None = None) -> dict:
    """A fact: `value` is the quantity as the receipt shows it; `phrase` is how it reads inside a sentence (the value verbatim
    within it); a word fact's phrase is its words."""
    iso = as_of.isoformat() if isinstance(as_of, date) else as_of
    value = str(value)
    return {"id": fid, "name": name, "value": value, "as_of": iso, "source": source, "kind": kind,
            "phrase": phrase if phrase is not None else (value if kind == "word" else phrase_for(name, value))}


def number_facts(sentences: list[dict], questions: list[dict]) -> list[dict]:
    """Pure: every receipt the Overview and the strip show, as facts with stable ids. The same name with a different value
    (two questions' "report date") keeps both under ids suffixed by the question key; the same name and value appears once."""
    facts: dict[str, dict] = {}
    seen: dict[tuple[str, str], str] = {}
    def add(inp: dict, suffix: str):
        key = (inp["name"], inp["value"])
        if key in seen:
            return
        fid = slug(inp["name"])
        if fid in facts:
            fid = f"{fid}_{slug(suffix)}"
        if fid in facts:
            return
        seen[key] = fid
        if inp["name"] == "1-day move window":
            m = _WINDOW_VALUE.search(inp["value"])
            if not m:
                return
            facts["move_session"] = _fact("move_session", "session the move was measured over", m.group("after"), inp.get("as_of"),
                                          f"{inp.get('source')}; {inp['value']}", phrase=f"over the next session, {m.group('after')}")
            return
        facts[fid] = _fact(fid, inp["name"], inp["value"], inp.get("as_of"), inp.get("source"))
    for s in sentences:
        for inp in s.get("inputs", []):
            add(inp, s.get("key", "overview"))
    for q in questions:
        for inp in q.get("inputs", []):
            add(inp, q.get("key", "question"))
    return list(facts.values())


def volatility_word(rv_rank: float) -> str:
    """Pure: the stock's 20-day realized volatility against its own past year, in a word."""
    if rv_rank >= RV_ELEVATED_RANK:
        return "elevated"
    if rv_rank <= RV_QUIET_RANK:
        return "quiet"
    return "normal"


def word_facts(raw: dict) -> list[dict]:
    """Pure: the comparisons Ivy may state, each computed here from the same numbers the strip uses (never by the model)."""
    out: list[dict] = []
    imp, typ = raw.get("implied"), raw.get("typical_abs")
    if imp and typ:
        out.append(_fact("implied_vs_typical", "implied move against the typical move", compare_moves(imp["implied_pct"] * 100, typ), imp["chain_date"],
                         "services/move_comparison: over 1.2x is more than usual, under 0.8x less", "word"))
    bars, quote = raw.get("bars") or {}, raw.get("quote_price")
    price = quote if quote is not None else bars.get("last_close")
    if price is not None and bars.get("high_52w"):
        below = (bars["high_52w"] - price) / bars["high_52w"] * 100
        near = below < B.NEAR_HIGH_PCT
        out.append(_fact("price_vs_52_week_high", "price against the 52-week high", "near" if near else "below", bars.get("high_52w_date"),
                         f"within {B.NEAR_HIGH_PCT}% of the highest stored close is near", "word", phrase="near its 52-week high" if near else "below its 52-week high"))
        if bars.get("high_52w_date"):
            out.append(_fact("52_week_high_date", "52-week high date", B.fmt_date(bars["high_52w_date"]), bars["high_52w_date"], "stored daily closes, the day of the highest close"))
    rv = raw.get("rv")
    if rv:
        out.append(_fact("volatility_vs_year", "20-day realized volatility against the stock's own past year", volatility_word(rv["rv_rank"]), rv["as_of"],
                         f"stored volatility rank: at or above the {RV_ELEVATED_RANK}th percentile is elevated, at or below the {RV_QUIET_RANK}th quiet", "word"))
    last = raw.get("last_report")
    if last:
        if last.get("timing") in B.TIMING_PHRASE:
            out.append(_fact("last_report_timing", "last report timing", B.TIMING_PHRASE[last["timing"]], last["event_date"], "earnings calendar, report timing", "word"))
        if last.get("move_pct") is not None and typ:
            out.append(_fact("last_move_vs_typical", "move after the last report against the typical move", compare_moves(abs(last["move_pct"]), typ), last["event_date"],
                             "services/move_comparison: over 1.2x the typical move is more than usual, under 0.8x less", "word"))
        if last.get("outcome"):
            out.append(_fact("last_report_outcome", "last report against the EPS estimate", last["outcome"], last["event_date"], "reported EPS against the analyst consensus estimate", "word"))
        if last.get("move_pct") is not None:
            out.append(_fact("last_report_direction", "direction of the move after the last report", "rose" if last["move_pct"] > 0 else "fell" if last["move_pct"] < 0 else "unchanged",
                             last["event_date"], "sign of the stored 1-day move", "word"))
    nxt = raw.get("next_report")
    if nxt and nxt.get("date"):
        out.append(_fact("next_report_status", "next report date", "confirmed" if nxt.get("confirmation") == "confirmed" else "estimated", nxt["date"], nxt.get("note"), "word"))
        if nxt.get("timing") in B.TIMING_PHRASE:
            out.append(_fact("next_report_timing", "next report timing", B.TIMING_PHRASE[nxt["timing"]], nxt["date"], "earnings calendar, report timing", "word"))
    pe = raw.get("pe")
    if pe:
        if pe.get("sector") == "Real Estate":
            from app.services.questions import REIT_NOTE
            out.append({**_fact("earnings_measure_note", "how real estate companies are judged", REIT_NOTE, pe["as_of"], "services/questions REIT_NOTE", "note"),
                        "hidden": True, "applies_to": ("p_e", "five_year_median_p_e", "sessions_below_today_s_p_e", "sector_median_p_e", "pe_vs_history", "pe_vs_sector")})
        from app.services.questions import pe_history_words
        if pe.get("hist_median") is not None:
            out.append(_fact("pe_vs_history", "P/E against its five-year median", pe_history_words(pe["pe"], pe["hist_median"]),
                             pe["as_of"], "stored P/E against its five-year median, judged at one decimal", "word"))
        if pe.get("sector_median") is not None:
            out.append(_fact("pe_vs_sector", "P/E against its sector median", pe_history_words(pe["pe"], pe["sector_median"]),
                             pe["as_of"], "stored P/E against its sector median, judged at one decimal", "word"))
    div = raw.get("dividend")
    if div:
        out.append(_fact("dividend_status", "next dividend", "declared" if div.get("declared_on") else "estimated", div.get("declared_on") or div.get("ex_date"), "events (ex_dividend)", "word"))
    return out


def fingerprint(facts: list[dict]) -> str:
    """Pure: a hash of every fact's id, value and date; the cache is valid while it is unchanged."""
    return hashlib.sha256(json.dumps(sorted((f["id"], f["value"], f["as_of"] or "") for f in facts)).encode()).hexdigest()[:16]


def day_phrase(d: date) -> str:
    """"Wednesday, Oct 21": the weekday a visitor plans around."""
    return d.strftime("%A, ") + B.fmt_date(d).rsplit(",", 1)[0]


def close_phrase(chain_date: date, today: date) -> str:
    """"as of Friday's close" within the week, else "as of the Oct 9 close"."""
    days = (today - chain_date).days
    return f"as of {chain_date.strftime('%A')}'s close" if 0 <= days <= 6 else f"as of the {B.fmt_date(chain_date).rsplit(',', 1)[0]} close"


async def event_facts(db: AsyncSession, symbol: str, raw: dict, today: date) -> list[dict]:
    """The dates a visitor plans around: the next report's day and timing, the session the stock reacts on, the expirations before
    and after it from the serving chain, the implied move by the first expiration after the report (dated by its chain), and how
    often the stock rose after its last reports."""
    from app.scripts.ivy_v3_pull import next_session
    from app.services import chain_store
    from app.services.chain_shadow import counts_for_report
    from app.services.implied_move import straddle_implied_move
    out: list[dict] = []
    nxt = raw.get("next_report") or {}
    d = nxt.get("date")
    if d and d >= today:
        timing = (nxt.get("timing") or "").lower()
        out.append(_fact("next_report_day", "next report day", day_phrase(d), d, "earnings calendar", phrase=day_phrase(d)))
        react = d if timing == "bmo" else next_session(d)
        out.append(_fact("reaction_session", "session the stock reacts on", day_phrase(react), react,
                         "the report day for a before-open report, the next session for an after-close one", phrase=day_phrase(react)))
        exps = [e for e in await chain_store.get_ingested_expirations(db, symbol) if e >= today.isoformat()]
        chain_date = await chain_store.get_latest_chain_date(db, symbol) if exps else None
        before = [e for e in exps if not counts_for_report(e, d.isoformat(), timing or None)]
        after = [e for e in exps if counts_for_report(e, d.isoformat(), timing or None)]
        if before:
            e = date.fromisoformat(before[-1])
            out.append(_fact("last_expiration_before_report", "last expiration before the report", B.fmt_date(e).rsplit(",", 1)[0], chain_date,
                             "options chain, the expirations listed", phrase=day_phrase(e)))
        if after:
            e = date.fromisoformat(after[0])
            out.append(_fact("first_expiration_after_report", "first expiration after the report", B.fmt_date(e).rsplit(",", 1)[0], chain_date,
                             "options chain, the expirations listed", phrase=day_phrase(e)))
            got = await chain_store.get_chain(db, symbol, after[0])
            if got and got[1] and chain_store.is_fresh(got[1], today=today):
                chain, cd = got[0], date.fromisoformat(str(got[1])[:10])
                spot = chain.get("underlying_price") or raw.get("quote_price")
                im = straddle_implied_move(chain.get("calls") or [], chain.get("puts") or [], spot)
                if im is not None:
                    pct = f"{im.pct * 100:.1f}%"
                    out.append(_fact("implied_move_by_first_expiration_after_report", "implied move by the first expiration after the report", f"±{pct}", cd,
                                     "at-the-money straddle over the stock price, the stored chain for that expiration",
                                     phrase=f"about {pct} by {B.fmt_date(e).rsplit(',', 1)[0]} {close_phrase(cd, today)}"))
    rows = (await db.execute(text("""SELECT hr.event_date, hr.pct_change_1d FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
        WHERE t.symbol = :s AND hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL ORDER BY hr.event_date DESC LIMIT 20"""), {"s": symbol})).all()
    if rows:
        ups = sum(1 for _, m in rows if float(m) > 0)
        out.append(_fact("reports_up", "reports followed by a rise", str(ups), rows[0][0], "stored earnings reactions, the 1-day move after each report",
                         phrase=f"up after {ups} of its last {len(rows)} reports"))
    return out


def date_phrases(facts: list[dict]) -> None:
    """Every figure that is not today's carries its date: the phrases of the dated facts the strip hands over."""
    for f in facts:
        if not f.get("as_of") or len(f["as_of"]) < 10:
            continue
        try:
            when = B.fmt_date(date.fromisoformat(f["as_of"][:10]))
        except ValueError:
            continue
        if f["id"] in ("typical_move", "typical_move_after_a_report"):
            f["phrase"] = f"{f['value']} on a typical report as of its {when} report"
        elif f["id"] in ("largest_up_move", "largest_down_move"):
            f["phrase"] = f"{f['phrase']} on {when}"
        elif f["id"] == "20_day_realized_volatility":
            f["phrase"] = f"{f['value']} annualized as of {when}"
        elif f["id"] == "last_close":
            f["phrase"] = f"{f['value']} on {when}"                       # the name says "last close"; the phrase never repeats it


async def fact_pack(db: AsyncSession, symbol: str, today: date | None = None) -> dict:
    """{symbol, name, facts, context, fingerprint}: the receipts behind the Overview and every qualifying strip question,
    plus the word-valued comparisons, the event facts (event_facts), and the sentences the page already shows as context."""
    from app.services.briefing_build import build_briefing, build_questions
    today = today or date.today()
    raw: dict = {}
    brief = await build_briefing(db, symbol, today)
    qs = await build_questions(db, symbol, today, raw=raw, all_candidates=True)
    facts = with_denominators(number_facts(brief["sentences"], qs["questions"])) + word_facts(raw) + await event_facts(db, symbol, raw, today)
    date_phrases(facts)
    last = raw.get("last_report") or {}
    for f in facts:
        if f["id"] == "move_session" and last.get("timing") == "bmo":
            f["phrase"] = f"over that session, {f['value']}"
    context = [s["text"] for s in brief["sentences"]] + [f"Q: {q['question']} A: {q['data']}" for q in qs["questions"]]
    return {"symbol": brief["symbol"], "name": qs.get("name") or brief.get("name") or brief["symbol"], "facts": facts, "context": context, "fingerprint": fingerprint(facts),
            "active": brief.get("state") is None and bool(brief["sentences"] or qs["questions"])}


# ── the prompt ───────────────────────────────────────────────────────────────

KIND_GUIDANCE = {
    "timing": "The visitor is deciding whether to act now. Lead with the next report and how many days away it is, then what the options are pricing against the stock's typical earnings move, where the price sits against its 52-week high and its three-month trend, and whether it is moving more or less than usual.",
    "direction": "The visitor wants to know what the stock will do after the event. Four short sentences at most: how often it rose after its past reports, the typical size with the largest move each way, then what the options are pricing now. Never predict, and never say no one knows.",
    "quality": "The visitor is judging the business. Lead with what the company does and its recent results in plain words, then how its price has moved; a P/E is compared with its own history and its sector, never called cheap or expensive.",
    "options_planning": "The visitor is planning an option. Lead with the next report's day and timing, the session the stock reacts on, which expiration ends before that reaction and which first includes it, and what the options are pricing against the typical move.",
    "extraction": "The visitor asked for a raw series, table or export (daily closes, price history, every strike and bid, OHLC bars, a CSV). The system itself writes the sentence that declines the list and points to the chart and the Options section; do not write it, and list nothing. Answer what the person is after in two or three sentences: for a price list, where the price sits against its 52-week high and its trend; for a chain or strikes, the next expiration and what the options are pricing against the typical move; for bars, how much it moves on a typical day and lately.",
    "covered_other": "Answer the question asked, with the figure that settles it and one clause on why it matters.",
    "not_covered": "The facts do not hold what was asked. In one plain sentence say what Ivy does not track, then give the closest thing she does hold.",
}

TARGET_EXAMPLE = ("Tesla reports after the close on Wednesday, Oct 21, so the stock reacts Thursday, Oct 22. An option that expires on or before Oct 21 "
                  "ends before that reaction. Friday, Oct 23 is the nearest expiration that includes it. Options covering the report cost more because "
                  "they price in the earnings move, about 7.5% by Oct 23 as of Friday's close, and Tesla has moved about 8.6% on a typical report.")


def build_prompt(pack: dict, question: str, kind: str = "covered_other") -> str:
    hidden = BEAT_FACTS if kind in DECISION_KINDS else set()
    lines = [f"{{fact:{f['id']}}} = {f['name']}: {f['value']}" + (f" (as of {f['as_of']})" if f["as_of"] else "")
             + (" [word]" if f["kind"] == "word" else "") + (f' → reads "{f["phrase"]}"' if f.get("phrase") and f["phrase"] != f["value"] else "")
             for f in pack["facts"] if not f.get("hidden") and f["id"] not in hidden]
    context = "\n".join(f"- {c}" for c in pack["context"]) or "- (nothing shown yet)"
    return f"""You are Ivy, an analyst explaining {pack['name']} ({pack['symbol']}) to someone new to investing who typed a question on the stock's page. You may use ONLY the stored facts below. Nothing else you know about the company, its products, its valuation or the market may enter the answer.

FACTS (each has an id; a [word] fact is a precomputed comparison you may state in those words):
{chr(10).join(lines) or '(no facts stored)'}

WHAT THE PAGE ALREADY SAYS (for context; the numbers in it are the facts above):
{context}

QUESTION: {question}
KIND OF QUESTION: {kind}. {KIND_GUIDANCE.get(kind, KIND_GUIDANCE['covered_other'])}

THE VOICE (an example of the target, for "I'm looking to buy a call on Tesla, are there dates that matter for my expiration?"):
"{TARGET_EXAMPLE}"

RULES
1. First line: COVERED: yes, partly, no or off. "yes" when the facts answer the question; "partly" when they bear on it but do not answer it; "no" when the question is about this company or its stock but nothing above bears on it; "off" when the question is not about this company's stock at all.
2. Then the answer: under {WORD_CAP} words (aim for about sixty), at most {MAX_SENTENCES} short sentences, plain English a beginner follows. Answer the decision behind the question the way an analyst explains it. Facts first. Every figure comes with one clause on why it matters.
3. Never type a number. No digits, no currency signs, no percent signs, no number words (one, two ... twenty, twice, double, triple, half, a quarter of, dozen). Every quantity, date, price, percentage or count is written as its placeholder, exactly {{fact:id}}, and the system inserts the value with its date. Describe time windows in words ("the next session", "the trailing month") rather than with numbers.
3a. A fact's "as of" date is not a fact: cite a date only through a fact whose value is that date. Each placeholder expands to the quoted "reads" phrase when one is given (otherwise to the bare value), so write the sentence around that phrase and do not repeat words the phrase already carries: a phrase that already names the sample ("on a typical report as of its ... report") or the comparison ("below its 52-week high") is complete; add nothing about the same quantity after it.
4. State a comparison (more than usual, below its 52-week high, quiet, elevated, confirmed, estimated, after the close) only when a [word] fact above says exactly that; the comparison words come from the same thresholds the page uses.
5. Correct tense: a report that has not happened "reports"; a past one "reported". Never mention your own sources or the page: no "the facts show", "the data indicates", "this page", "the facts here", "stored". When something relevant is not covered (news, product events, guidance), say it in one plain sentence in your own words ("Ivy doesn't track product events or news, so check those before you choose"), never as a list of what is missing.
6. Never give a recommendation, a target, or an opinion about value, and never use words that imply a call: cheap, a bargain, expensive, overpriced, a good entry. The system adds the one closing line about calls itself; do not write it. Do not mention earnings beats or misses in a decision question.
7. No unexplained terms: never "IV", "RV", "ATM", "straddle"; say "implied move", "typical move", "an at-the-money option".
8. COVERED: off: write no answer text; the system shows a fixed sentence. COVERED: no: one plain sentence on what Ivy does not track, then the closest thing the facts hold, with placeholders.
9. No greetings, no preamble, no bullet points, no markdown, no hedging about being an AI.
10. Never a list, table, CSV or run of figures: an answer explains a handful of figures; price history and option chains stay on the chart and in the Options section.

Answer:"""


# ── output check and comparison verification ─────────────────────────────────

def check_output(text_: str, fact_ids: set[str], note_ids: set[str] | None = None) -> list[str]:
    """Pure: every reason the model's text cannot be shown. Empty when it passes. A note fact placed by the model is a problem:
    the system appends notes itself."""
    problems: list[str] = []
    used = PLACEHOLDER.findall(text_)
    unknown = sorted({u for u in used if u not in fact_ids})
    if unknown:
        problems.append(f"unknown fact id(s): {', '.join(unknown)}")
    placed_notes = sorted({u for u in used if u in (note_ids or set())})
    if placed_notes:
        problems.append(f"a note fact placed by the model: {', '.join(placed_notes)}")
    stripped = _WINDOW.sub(" ", PLACEHOLDER.sub(" ", text_))
    typed = re.findall(r"\S*[0-9$%€£]\S*", stripped)
    if typed:
        problems.append("a digit, currency sign or percent sign outside a placeholder: " + ", ".join(sorted(set(typed))[:5]))
    m = NUMBER_WORD.search(stripped)
    if m:
        problems.append(f"number word: {m.group(0)}")
    if HALF.search(stripped):
        problems.append("number word: half")
    if QUARTER_FRACTION.search(stripped):
        problems.append("number word: quarter as a fraction")
    if RECOMMENDATION.search(stripped):
        problems.append("recommendation language")
    m = VALUATION_VERDICTS.search(stripped)
    if m:
        problems.append(f"valuation verdict: {m.group(0)}")
    m = FORBIDDEN_PHRASES.search(stripped)
    if m:
        problems.append(f"a phrase that implies a call or names her sources: {m.group(0)}")
    m = JARGON.search(stripped) or JARGON_WORDS.search(stripped)
    if m:
        problems.append(f"an unexplained term: {m.group(0)}")
    if len(sentences(text_)) > MAX_SENTENCES:
        problems.append(f"more than {MAX_SENTENCES} sentences")
    if "{" in PLACEHOLDER.sub("", text_) or "}" in PLACEHOLDER.sub("", text_):
        problems.append("a malformed placeholder")
    return problems


def verify_comparisons(text_: str, facts: list[dict]) -> list[str]:
    """Pure: every comparison phrase in the text that no word fact supports (missing, or stating the other value)."""
    words = {f["id"]: f["value"] for f in facts if f["kind"] == "word"}
    problems: list[str] = []
    for pattern, group in COMPARISONS:
        m = pattern.search(text_)
        if not m:
            continue
        present = {fid: words[fid] for fid in group if fid in words}
        if not present:
            problems.append(f'"{m.group(0)}" has no stored comparison behind it')
        elif not any(present[fid] == asserted for fid, asserted in group.items() if fid in present):
            problems.append(f'"{m.group(0)}" contradicts the stored comparison ({", ".join(sorted(set(present.values())))})')
    return problems


_ABBREVIATION = re.compile(r"\b(?:Inc|Co|Corp|Ltd|Jr|Sr|No|vs|U\.S|L\.P|S\.A|N\.V|plc|Cos|Bros)\.$")


def sentences(text_: str) -> list[str]:
    """Pure: sentences split at a terminal mark; "Inc." and its kind, and a mark followed by a lowercase word, never end one."""
    out: list[str] = []
    for part in SENTENCE_END.split(text_.strip()):
        if not part:
            continue
        if out and (_ABBREVIATION.search(out[-1]) or part[:1].islower()):
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return out


def parse_model_output(content: str) -> tuple[str, str]:
    """Pure: (covered, answer) from the model's output; covered defaults to "partly" when the first line is missing."""
    lines = content.strip().splitlines()
    covered = "partly"
    if lines and lines[0].strip().upper().startswith("COVERED:"):
        covered = lines[0].split(":", 1)[1].strip().lower().rstrip(".") or "partly"
        lines = lines[1:]
    if covered not in ("yes", "partly", "no", "off"):
        covered = "partly"
    return covered, " ".join(l.strip() for l in lines if l.strip())


def absorb_literals(text_: str, facts: list[dict]) -> str:
    """Pure: a fact's phrase or value the model typed verbatim becomes its placeholder (longest first, never inside one already),
    so a copied "Oct 1, 2026" still renders from the fact with its receipt and the no-typed-numbers check judges only what is
    not a stored value. A word fact's words are left alone (they are prose)."""
    spans = [(m.start(), m.end()) for m in PLACEHOLDER.finditer(text_)]
    def inside(i: int) -> bool:
        return any(a <= i < b for a, b in spans)
    for f in sorted((f for f in facts if f["kind"] == "number"), key=lambda f: -len(f.get("phrase") or f["value"])):
        for literal in sorted({f.get("phrase") or f["value"], f["value"]}, key=len, reverse=True):
            if not literal or not re.search(r"\d", literal):
                continue
            pos = 0
            while True:
                i = text_.find(literal, pos)
                if i < 0:
                    break
                if inside(i):
                    pos = i + 1
                    continue
                ph = f"{{fact:{f['id']}}}"
                text_ = text_[:i] + ph + text_[i + len(literal):]
                spans = [(m.start(), m.end()) for m in PLACEHOLDER.finditer(text_)]
                pos = i + len(ph)
    return text_


_DOUBLED = re.compile(r"\b([A-Za-z]+) \1\b", re.I)


def collapse_doubled_words(text_: str) -> str:
    """Pure: one identical word written twice in a row ("after after the close", when the model's word meets the fact's) appears
    once. Only a single doubled word; a repeated phrase of four or more words is rejected, never patched (repeated_phrase)."""
    return _DOUBLED.sub(r"\1", text_)


def render(text_: str, facts: list[dict]) -> tuple[str, list[dict]]:
    """Pure: the text with every placeholder replaced by its fact's value, and the inputs (receipts) for the frontend's tokenizer
    in the order used. A word fact substitutes its words and carries no receipt."""
    by_id = {f["id"]: f for f in facts}
    inputs: list[dict] = []
    def add_input(f: dict) -> None:
        if f["kind"] == "number" and not any(i["name"] == f["name"] and i["value"] == f["value"] for i in inputs):
            inputs.append({"name": f["name"], "value": f["value"], "as_of": f["as_of"], "source": f["source"]})
    used: set[str] = set()
    def sub(m: re.Match) -> str:
        f = by_id.get(m.group(1))
        if f is None:
            return m.group(0)                      # an id the model invented: check_output rejects the draft; nothing to render here
        used.add(f["id"])
        add_input(f)
        for cid in f.get("companions", []):          # a denominator carried in the phrase gets its receipt too
            if cid in by_id:
                add_input(by_id[cid])
        return f.get("phrase") or f["value"]
    from app.services.anthropic_client import _scrub_dashes
    rendered = collapse_doubled_words(_scrub_dashes(PLACEHOLDER.sub(sub, text_)))
    return rendered, inputs


def notes_for(text_: str, facts: list[dict]) -> list[str]:
    """Pure: the sentence-valued facts (kind note) whose subject the text placed: appended by the system as their own final
    sentences, never written by the model (a note never appears as a placeholder in the prompt)."""
    used = set(PLACEHOLDER.findall(text_))
    return [f["value"] for f in facts if f["kind"] == "note" and used & set(f.get("applies_to", ()))]


# ── the verifier ─────────────────────────────────────────────────────────────

def build_verification_prompt(pack: dict, rendered: str) -> str:
    facts = "\n".join(f"- {f['name']}: {f['value']}" + (f" (as of {f['as_of']})" if f["as_of"] else "")
                      + (f' → the answer reads it as "{f["phrase"]}"' if f.get("phrase") and f["phrase"] != f["value"] else "") for f in pack["facts"])
    return f"""You are a rigorous fact-checker. Check each sentence of the answer below against the stored facts ONLY.

STORED FACTS about {pack['name']} ({pack['symbol']}):
{facts or '(none)'}

ANSWER:
{rendered}

RULES
- "supported": every factual claim in the sentence is confirmed by the facts, or the sentence says what Ivy does not track (news, product events, a visitor's own situation) and indeed no fact covers it, or the sentence explains an idea in general terms with no factual claim about this company. A clause that only says why a confirmed figure matters ("so the next session carries uncertainty", "which matters because options price that move") does not make a supported sentence unsupported.
- "unsupported": the sentence makes a claim about this company or its stock that the facts do not confirm (outside knowledge, an inference not in the facts).
- "contradicted": the sentence conflicts with a fact.
- A comparison between two figures the facts confirm ("close to", "about the same as", "more than", "wider than") is supported when the arithmetic holds; a sentence that strings several confirmed figures together is supported.
- A fact's "reads" wording is the exact text the answer uses for it, date clause included: "as of its Aug 5, 2026 report" names that fact's as-of date, "as of Friday's close" names the chain's date, and a weekday beside a date was computed from that date. Wherever that wording appears, the fact is confirmed.
- Bias toward "unsupported" when in doubt about a claim; never mark a sentence unsupported for its explanation of why a confirmed figure matters. Use no outside knowledge.

Return JSON only: {{"sentences": [{{"text": "...", "status": "supported|unsupported|contradicted", "evidence": "..."}}]}} with one entry per sentence of the answer, in order."""


def apply_verdicts(rendered_sentences: list[str], verdicts: list[dict]) -> tuple[list[str], list[str]]:
    """Pure: (kept, dropped) sentences; a sentence is kept only when its verdict is "supported". A verdict list that does not
    line up with the sentences keeps nothing (nothing unverified reaches the screen)."""
    if len(verdicts) != len(rendered_sentences):
        return [], list(rendered_sentences)
    kept = [s for s, v in zip(rendered_sentences, verdicts) if v.get("status") == "supported"]
    dropped = [s for s, v in zip(rendered_sentences, verdicts) if v.get("status") != "supported"]
    return kept, dropped


def parse_verdicts(content: str) -> list[dict]:
    body = content.strip()
    if body.startswith("```"):
        body = body.split("```")[1]
        body = body[4:] if body.startswith("json") else body
    data = json.loads(body.strip())
    return list(data.get("sentences", []))


# ── normalization and cache ──────────────────────────────────────────────────

def normalize_question(question: str, symbol: str, name: str | None) -> str:
    """Pure: lowercase, no punctuation, the ticker and company name folded away, stopwords dropped, synonyms folded, words sorted."""
    q = question.lower()
    q = re.sub(r"[^a-z0-9\s]", " ", q)
    drop = {symbol.lower()} | {w for w in re.sub(r"[^a-z0-9\s]", " ", (name or "").lower()).split() if len(w) > 2}
    words = []
    for w in q.split():
        if w in drop or w in STOPWORDS:
            continue
        words.append(_SYN_INDEX.get(w, w))
    return " ".join(sorted(set(words)))


def cache_key(symbol: str, normalized: str, fp: str) -> str:
    return hashlib.sha256(f"v{CACHE_VERSION}|{symbol}|{normalized}|{fp}".encode()).hexdigest()[:32]


async def cached_answer(db: AsyncSession, key: str) -> dict | None:
    row = (await db.execute(text("SELECT answer FROM ask_log WHERE cache_key = :k AND answer IS NOT NULL AND verdict IN ('verified', 'partly_dropped', 'not_covered', 'off_topic', 'declined') "
                                 "ORDER BY created_at DESC LIMIT 1"), {"k": key})).first()
    return row[0] if row else None


async def log_question(db: AsyncSession, *, symbol: str, question: str, normalized: str, key: str, covered: bool, verdict: str, answer: dict | None,
                       model: str | None, input_tokens: int | None, output_tokens: int | None, cost: float | None, cached: bool, ip_hash: str | None) -> None:
    await db.execute(text("""INSERT INTO ask_log (symbol, question, normalized, cache_key, covered, verdict, answer, model, input_tokens, output_tokens, cost_usd, cached, ip_hash)
                             VALUES (:s, :q, :n, :k, :c, :v, CAST(:a AS jsonb), :m, :i, :o, :cost, :cached, :ip)"""),
                     {"s": symbol, "q": question[:MAX_QUESTION_CHARS], "n": normalized, "k": key, "c": covered, "v": verdict, "a": json.dumps(answer) if answer is not None else None,
                      "m": model, "i": input_tokens, "o": output_tokens, "cost": cost, "cached": cached, "ip": ip_hash})
    await db.commit()


async def spend_today(db: AsyncSession, now: datetime | None = None) -> float:
    raw = await get_value(db, f"{SPEND_KEY}:{(now or datetime.now(timezone.utc)).strftime('%Y-%m-%d')}")
    return float(raw) if raw else 0.0


async def add_spend(db: AsyncSession, cost: float | None, now: datetime | None = None) -> None:
    if not cost:
        return
    now = now or datetime.now(timezone.utc)
    await set_value(db, f"{SPEND_KEY}:{now.strftime('%Y-%m-%d')}", f"{await spend_today(db, now) + cost:.5f}")
    from app.services import ai_spend
    await ai_spend.add(db, cost, now, commit=False)          # the site-wide cap counts every feature's spend
    await db.commit()


# ── the answer ───────────────────────────────────────────────────────────────

RULE = ("Ivy wrote the words from this stock's stored facts and typed no number: every quantity was inserted from a stored fact with its receipt, "
        "every comparison word was checked against a stored comparison, and each sentence was checked against those facts before display; "
        "a sentence the check did not support was dropped.")


def not_covered_answer(pack: dict, question: str) -> dict:
    """One plain sentence, never a list of what is missing."""
    return {"key": "ask", "question": question, "data": f"Ivy doesn't track that for {pack['name']}, so check it elsewhere before you choose; she can answer about {can_answer_clause(pack)}.",
            "idea": "", "inputs": [], "as_of": None, "as_of_kind": "observed", "rule": RULE}


def word_count(text_: str) -> int:
    return len(re.findall(r"[A-Za-z0-9$%.,+±-]+", text_))


def cut_to_cap(kept: list[str], cap: int = WORD_CAP) -> list[str]:
    """Pure: the longest run of leading sentences within the cap (at least the first)."""
    out: list[str] = []
    for sn in kept:
        if out and word_count(" ".join(out + [sn])) > cap:
            break
        out.append(sn)
    return out


TIMEOUT_LINE = "Ivy couldn't finish an answer about {name} in time. Try again in a minute; nothing was charged to your limit."


def timeout_answer(name: str, question: str) -> dict:
    """What a visitor sees when a stage ran past its deadline: a plain sentence, no partial answer."""
    return {"key": "ask", "question": question, "data": TIMEOUT_LINE.format(name=name), "idea": "", "inputs": [], "as_of": None,
            "as_of_kind": "observed", "rule": RULE}


async def pack_within(db: AsyncSession, symbol: str) -> dict | None:
    """The fact pack, or None past PACK_SECONDS."""
    try:
        return await asyncio.wait_for(fact_pack(db, symbol), PACK_SECONDS)
    except asyncio.TimeoutError:
        return None


async def answer_within(db: AsyncSession, pack: dict, question: str, *, client=None, kind: str = "covered_other") -> dict:
    """answer_question within ANSWER_SECONDS; past it, verdict "timeout" with timeout_answer and no cost recorded (a call cut off
    mid-flight reports no usage)."""
    try:
        return await asyncio.wait_for(answer_question(db, pack, question, client=client, kind=kind), ANSWER_SECONDS)
    except asyncio.TimeoutError:
        return {"covered": "no", "verdict": "timeout", "answer": timeout_answer(pack["name"], question), "model": None, "input_tokens": None,
                "output_tokens": None, "cost": 0.0, "problems": [f"no answer within {ANSWER_SECONDS}s"]}


def unchecked_answer(pack: dict, question: str) -> dict:
    """What a visitor sees when no draft passed the checks: a plain sentence, no guess."""
    return {"key": "ask", "question": question, "data": f"Ivy couldn't produce an answer about {pack['name']} that passed the checks for that question.", "idea": "",
            "inputs": [], "as_of": None, "as_of_kind": "observed", "rule": RULE}


def answer_payload(question: str, kept: list[str], inputs: list[dict], pack: dict) -> dict:
    as_of = max((i["as_of"] for i in inputs if i.get("as_of") and len(i["as_of"]) >= 10), default=None)
    today = date.today().isoformat()
    return {"key": "ask", "question": question, "data": " ".join(kept), "idea": "", "inputs": inputs,
            "as_of": (as_of[:10] if as_of and as_of[:10] <= today else None), "as_of_kind": "observed", "rule": RULE}


async def answer_question(db: AsyncSession, pack: dict, question: str, *, client=None, kind: str = "covered_other") -> dict:
    """Run the model, the output check, the comparison check, substitution and the verifier for one question against a fact pack.
    Returns {verdict, covered, answer, model, input_tokens, output_tokens, cost, problems, dropped, raw}. Charges and logs nothing."""
    client = client or ask_client()
    if kind == "off_topic":
        return {"covered": "off", "verdict": "off_topic", "answer": refusal_answer(pack, question), "model": None, "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
                "problems": [], "dropped": [], "raw": "", "retried": False, "kind": kind}
    pack = {**pack, "facts": [f for f in pack["facts"] if not (kind in DECISION_KINDS and f["id"] in BEAT_FACTS)]}
    prompt = build_prompt(pack, question, kind)
    gen = await client.generate_answer(prompt)
    covered, body = parse_model_output(gen["content"])
    body = absorb_literals(body, pack["facts"])
    tokens = {"input_tokens": gen["input_tokens"], "output_tokens": gen["output_tokens"]}
    cost = estimate_cost_usd(gen["model_used"], gen["input_tokens"], gen["output_tokens"]) or 0.0
    out = {"covered": covered, "model": gen["model_used"], "raw": gen["content"], **tokens, "problems": [], "dropped": [], "retried": False}
    ids, note_ids = {f["id"] for f in pack["facts"]}, {f["id"] for f in pack["facts"] if f["kind"] == "note"}
    def sentence_problems(text_: str) -> list[str]:
        rendered_, _ = render(text_, pack["facts"])
        reps = [r for r in (repeated_phrase(sn) for sn in sentences(rendered_)) if r]
        out_ = ([p for p in check_output(text_, ids, note_ids) if not p.startswith("more than")] + verify_comparisons(text_, pack["facts"])
                + [f'a sentence repeats the phrase "{r}"' for r in reps])
        if kind in DECISION_KINDS and BEAT_WORDS.search(PLACEHOLDER.sub(" ", text_)):
            out_.append("a beat or miss in a decision answer")
        return out_
    def all_problems(text_: str, raw: str) -> list[str]:
        rendered_, _ = render(text_, pack["facts"])
        out_ = sentence_problems(text_) + series_problems(text_, rendered_, raw)
        if len(sentences(text_)) > MAX_SENTENCES:
            out_.append(f"more than {MAX_SENTENCES} sentences")
        if word_count(rendered_) > WORD_CAP:
            out_.append(f"over {WORD_CAP} words ({word_count(rendered_)})")
        return out_
    def declined() -> dict:
        return {**out, "verdict": "declined", "answer": extraction_decline(pack, question), "problems": problems, "cost": cost}
    problems = all_problems(body, gen["content"])
    if problems:
        # one rewrite with the check's reasons; a draft that fails twice is never shown
        gen2 = await client.generate_answer(prompt + "\n\nYour previous draft was rejected for these reasons: " + "; ".join(problems)
                                            + ". Rewrite it so none applies (spell no number word; use placeholders; state only comparisons a [word] fact gives; "
                                            "do not repeat words a placeholder's phrase already carries; no list, table or run of figures).\n\nAnswer:")
        covered, body = parse_model_output(gen2["content"])
        body = absorb_literals(body, pack["facts"])
        out.update(covered=covered, raw=gen2["content"], retried=True, first_problems=problems)
        out["input_tokens"] += gen2["input_tokens"]; out["output_tokens"] += gen2["output_tokens"]
        cost += estimate_cost_usd(gen2["model_used"], gen2["input_tokens"], gen2["output_tokens"]) or 0.0
        problems = all_problems(body, gen2["content"])
        if series_problems(body, render(body, pack["facts"])[0], gen2["content"]):
            return declined()                           # a series twice: the helpful decline, never the list
        # a second draft: each sentence that still fails a check is dropped (recorded as dropped); the rest goes on to the verifier
        failing = [sn for sn in sentences(body) if sentence_problems(sn)]
        if failing:
            out["dropped"] = [render(sn, pack["facts"])[0] for sn in failing]
            body = " ".join(sn for sn in sentences(body) if sn not in failing)
            problems = [] if body.strip() else problems
        if problems and all(p.startswith("over ") or p.startswith("more than " + str(MAX_SENTENCES)) for p in problems):
            problems = []                               # still long: cut at a sentence end below, never rejected for length alone
    if problems:
        return declined() if kind == "extraction" else {**out, "verdict": "rejected", "answer": unchecked_answer(pack, question), "problems": problems, "cost": cost}
    if covered == "off":
        return {**out, "verdict": "off_topic", "answer": refusal_answer(pack, question), "cost": cost}
    if covered == "no" and not PLACEHOLDER.search(body):
        return {**out, "verdict": "not_covered", "answer": not_covered_answer(pack, question), "cost": cost}
    rendered, inputs = render(body, pack["facts"])
    notes = notes_for(body, pack["facts"])
    if notes:
        rendered = sentences(rendered)
        rendered = " ".join(rendered + notes)        # a sentence-valued fact closes the answer as its own sentence
    ver = await client.verify_research_note(build_verification_prompt(pack, rendered))
    vcost = estimate_cost_usd(ver["model_used"], ver["input_tokens"], ver["output_tokens"]) or 0.0
    out["input_tokens"] += ver["input_tokens"]; out["output_tokens"] += ver["output_tokens"]
    try:
        verdicts = parse_verdicts(ver["content"])
    except (ValueError, json.JSONDecodeError):
        verdicts = []
    kept, dropped = apply_verdicts(sentences(rendered), verdicts)
    dropped = out["dropped"] + dropped
    if not kept:
        if kind == "extraction":
            return {**out, "verdict": "declined", "answer": extraction_decline(pack, question), "dropped": dropped, "cost": cost + vcost, "problems": ["no sentence survived verification"]}
        return {**out, "verdict": "rejected", "answer": unchecked_answer(pack, question), "dropped": dropped, "cost": cost + vcost, "problems": ["no sentence survived verification"]}
    kept = cut_to_cap(kept, WORD_CAP - (word_count(EXTRACTION_LINE) if kind == "extraction" else 0))
    if kind == "extraction":
        kept = [EXTRACTION_LINE] + kept                   # the decline comes first, written by code; the explanation answers what was wanted
    if kind in DECISION_KINDS:
        kept = kept + [CLOSING_LINE]                      # exactly one closing line, appended by code, never written by the model
    used_inputs = [i for i in inputs if i["value"] in " ".join(kept)]
    return {**out, "verdict": "verified" if not dropped else "partly_dropped", "answer": answer_payload(question, kept, used_inputs, pack), "dropped": dropped, "cost": cost + vcost,
            "verifier": verdicts, "kind": kind}


def ip_hash(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:12]
