"""Ask Ivy: the free-text question box under the question strip (flag ASK_IVY_ENABLED, off in production).

Ivy answers only from this stock's stored facts and says plainly when they do not cover the question. The model (Sonnet)
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

MAX_SENTENCES = 3
MAX_QUESTION_CHARS = 300
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
    (re.compile(r"\bbelow (?:its|the|a) (?:52-week|year|yearly|one-year|twelve-month) high\b|\boff (?:its|the) high\b|\bunder its (?:52-week|year) high\b", re.I), {"price_vs_52w_high": "below"}),
    (re.compile(r"\b(?:at|near) (?:its|a|the) (?:52-week|year|yearly|one-year|twelve-month|new) high\b", re.I), {"price_vs_52w_high": "near"}),
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
]
VALUATION_VERDICTS = re.compile(r"\b(?:cheap|expensive|undervalued|overvalued|pricey|a bargain|overpriced|underpriced)\b", re.I)   # a ratio is never a verdict


# ── deterministic classifiers: advice and off-topic questions never reach the model ──────────────────────────────

ADVICE_ANSWER = "Ivy cannot give investment advice."
OFF_TOPIC_ANSWER = "Ivy only answers questions about {name}'s stock."
# whether to buy, sell or hold; whether it is a good time; whether it is worth it (any phrasing of the person's own decision)
ADVICE = re.compile(
    r"\b(?:should|shall|do|could|would|can|ought)\s+(?:i|we|you|one|someone|a person|an investor)\b[^?.]{0,40}\b(?:buy|sell|hold|short|invest|get in|get out|add|trim|dump|load up|take profits?|cash out|keep holding|stay in|enter|exit)\b"
    r"|\b(?:is|was|would|will|does) (?:it|this|that|now|today|[A-Za-z.&' ]{1,40}) (?:a )?(?:good|bad|smart|wise|right|great|terrible|poor|best|worst|ok|okay|safe) (?:time|moment|idea|bet|buy|sell|investment|stock to buy|stock to own|entry|exit|point)\b"
    r"|\b(?:good|bad|smart|wise|right|great|best|worst|safe) (?:time|moment|idea|entry|exit) to (?:buy|sell|hold|invest|short|enter|exit|add|trim)\b"
    r"|\bworth (?:it|buying|selling|holding|owning|investing|a buy|the risk|getting into|picking up|adding)\b"
    r"|\b(?:is|was) (?:it|this|[A-Za-z.&' ]{1,40}) (?:a |an )?(?:buy|sell|hold|strong buy|strong sell|screaming buy|good buy|good investment|bad investment|safe investment|good stock to buy)\b"
    r"|\bbuy or sell\b|\bbuy,? sell,? or hold\b|\bbuy now\b|\bsell now\b|\btime to (?:buy|sell)\b|\bwhat should i do\b|\bwhat would you do\b|\brecommend(?:ation)?\b|\badvice\b"
    r"|\bshould i (?:be )?(?:buying|selling|holding|worried|concerned)\b|\bget in now\b|\bget out now\b|\bjump in\b|\bbail\b",
    re.I)
# clearly off this stock: chit-chat, other subjects, questions about Ivy herself; everything else is judged by the fact pack
OFF_TOPIC = re.compile(
    r"^\s*(?:hi|hello|hey|yo|thanks?|thank you|ok|okay|test|testing)\b[\s!.?]*$"
    r"|\b(?:weather|recipe|joke|poem|song|lyrics|movie|football|soccer|basketball|baseball|election|president|bitcoin|ethereum|crypto|gold price|oil price|mortgage rate|homework|translate|capital of|who are you|what are you|are you (?:an ai|a bot|human|chatgpt|claude)|what model|how do you work|who made you|meaning of life)\b",
    re.I)
STOCK_WORDS = re.compile(r"\b(?:stock|share|shares|price|earnings|report|dividend|move|moved|volatil|eps|estimate|high|low|quarter|results|sector|market|value|cap|trade|trading|options?|implied|beat|miss|upgrade|downgrade|analyst|ex-dividend|rally|drop|fall|rise|gain|loss|return|chart|history|typical|usual|react|outlook|forecast|predict|expect|guidance|revenue|growth|profit|valuation|cheap|expensive|rich|p/e|pe ratio|multiple)\b", re.I)


def classify_question(question: str, symbol: str, name: str | None) -> str:
    """Pure: "advice" (buy, sell, hold, good time, worth it), "off_topic" (chit-chat, another subject, nothing about a stock),
    else "normal" (predictions and everything else go to the model, which may still find the facts do not cover it)."""
    q = " ".join(question.split())
    if ADVICE.search(q):
        return "advice"
    if OFF_TOPIC.search(q):
        return "off_topic"
    mentions = symbol.lower() in q.lower() or bool(name and any(w.lower() in q.lower() for w in re.findall(r"[A-Za-z]{4,}", name)))
    if not STOCK_WORDS.search(q) and not mentions and not re.search(r"\b(?:it|its|it's|they|their|the company|this|that)\b", q, re.I):
        return "off_topic"
    return "normal"


def fixed_answer(kind: str, pack: dict, question: str) -> dict:
    text_ = ADVICE_ANSWER if kind == "advice" else OFF_TOPIC_ANSWER.format(name=pack["name"])
    return {"key": "ask", "question": question, "data": text_, "idea": "", "inputs": [], "as_of": None, "as_of_kind": "observed", "rule": RULE}


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
        out.append(_fact("price_vs_52w_high", "price against the 52-week high", "near" if below < B.NEAR_HIGH_PCT else "below", bars.get("high_52w_date"),
                         f"within {B.NEAR_HIGH_PCT}% of the highest stored close is near", "word"))
        if bars.get("high_52w_date"):
            out.append(_fact("52_week_high_date", "52-week high date", B.fmt_date(bars["high_52w_date"]), bars["high_52w_date"], "price_bars_shadow, the day of the highest close"))
    rv = raw.get("rv")
    if rv:
        out.append(_fact("volatility_vs_year", "20-day realized volatility against the stock's own past year", volatility_word(rv["rv_rank"]), rv["as_of"],
                         f"rv_snapshots.rv_rank: at or above the {RV_ELEVATED_RANK}th percentile is elevated, at or below the {RV_QUIET_RANK}th quiet", "word"))
    last = raw.get("last_report")
    if last:
        if last.get("timing") in B.TIMING_PHRASE:
            out.append(_fact("last_report_timing", "last report timing", B.TIMING_PHRASE[last["timing"]], last["event_date"], "events.report_timing", "word"))
        if last.get("move_pct") is not None and typ:
            out.append(_fact("last_move_vs_typical", "move after the last report against the typical move", compare_moves(abs(last["move_pct"]), typ), last["event_date"],
                             "services/move_comparison: over 1.2x the typical move is more than usual, under 0.8x less", "word"))
        if last.get("outcome"):
            out.append(_fact("last_report_outcome", "last report against the EPS estimate", last["outcome"], last["event_date"], "events.eps_actual against events.eps_estimate", "word"))
        if last.get("move_pct") is not None:
            out.append(_fact("last_report_direction", "direction of the move after the last report", "rose" if last["move_pct"] > 0 else "fell" if last["move_pct"] < 0 else "unchanged",
                             last["event_date"], "sign of the stored 1-day move", "word"))
    nxt = raw.get("next_report")
    if nxt and nxt.get("date"):
        out.append(_fact("next_report_status", "next report date", "confirmed" if nxt.get("confirmation") == "confirmed" else "estimated", nxt["date"], nxt.get("note"), "word"))
        if nxt.get("timing") in B.TIMING_PHRASE:
            out.append(_fact("next_report_timing", "next report timing", B.TIMING_PHRASE[nxt["timing"]], nxt["date"], "events.report_timing", "word"))
    pe = raw.get("pe")
    if pe:
        if pe.get("sector") == "Real Estate":
            from app.services.questions import REIT_NOTE
            out.append({**_fact("earnings_measure_note", "how real estate companies are judged", REIT_NOTE, pe["as_of"], "services/questions REIT_NOTE", "note"),
                        "hidden": True, "applies_to": ("p_e", "five_year_median_p_e", "sessions_below_today_s_p_e", "sector_median_p_e", "pe_vs_history", "pe_vs_sector")})
        if pe.get("hist_median") is not None:
            out.append(_fact("pe_vs_history", "P/E against its five-year median", "above" if pe["pe"] > pe["hist_median"] else "below" if pe["pe"] < pe["hist_median"] else "at",
                             pe["as_of"], "pe_snapshots.pe against pe_snapshots.hist_median", "word"))
        if pe.get("sector_median") is not None:
            out.append(_fact("pe_vs_sector", "P/E against its sector median", "above" if pe["pe"] > pe["sector_median"] else "below" if pe["pe"] < pe["sector_median"] else "at",
                             pe["as_of"], "pe_snapshots.pe against pe_sector_snapshots.median_pe", "word"))
    div = raw.get("dividend")
    if div:
        out.append(_fact("dividend_status", "next dividend", "declared" if div.get("declared_on") else "estimated", div.get("declared_on") or div.get("ex_date"), "events (ex_dividend)", "word"))
    return out


def fingerprint(facts: list[dict]) -> str:
    """Pure: a hash of every fact's id, value and date; the cache is valid while it is unchanged."""
    return hashlib.sha256(json.dumps(sorted((f["id"], f["value"], f["as_of"] or "") for f in facts)).encode()).hexdigest()[:16]


async def fact_pack(db: AsyncSession, symbol: str, today: date | None = None) -> dict:
    """{symbol, name, facts, context, fingerprint}: the receipts behind the Overview and every qualifying strip question,
    plus the word-valued comparisons, and the sentences the page already shows as context."""
    from app.services.briefing_build import build_briefing, build_questions
    today = today or date.today()
    raw: dict = {}
    brief = await build_briefing(db, symbol, today)
    qs = await build_questions(db, symbol, today, raw=raw, all_candidates=True)
    facts = with_denominators(number_facts(brief["sentences"], qs["questions"])) + word_facts(raw)
    last = raw.get("last_report") or {}
    for f in facts:
        if f["id"] == "move_session" and last.get("timing") == "bmo":
            f["phrase"] = f"over that session, {f['value']}"
    context = [s["text"] for s in brief["sentences"]] + [f"Q: {q['question']} A: {q['data']}" for q in qs["questions"]]
    return {"symbol": brief["symbol"], "name": qs.get("name") or brief.get("name") or brief["symbol"], "facts": facts, "context": context, "fingerprint": fingerprint(facts),
            "active": brief.get("state") is None and bool(brief["sentences"] or qs["questions"])}


# ── the prompt ───────────────────────────────────────────────────────────────

def build_prompt(pack: dict, question: str) -> str:
    lines = [f"{{fact:{f['id']}}} = {f['name']}: {f['value']}" + (f" (as of {f['as_of']})" if f["as_of"] else "")
             + (" [word]" if f["kind"] == "word" else "") + (f' → reads "{f["phrase"]}"' if f.get("phrase") and f["phrase"] != f["value"] else "")
             for f in pack["facts"] if not f.get("hidden")]
    context = "\n".join(f"- {c}" for c in pack["context"]) or "- (nothing shown yet)"
    return f"""You are Ivy, answering a visitor's question about {pack['name']} ({pack['symbol']}) on a stock page. You may use ONLY the stored facts below. Nothing else you know about the company, its products, its valuation or the market may enter the answer.

FACTS (each has an id; a [word] fact is a precomputed comparison you may state in those words):
{chr(10).join(lines) or '(no facts stored)'}

WHAT THE PAGE ALREADY SAYS (for context; the numbers in it are the facts above):
{context}

QUESTION: {question}

RULES
1. First line: COVERED: yes, partly, no or off. "yes" when the facts answer the question; "partly" when they bear on it but do not answer it; "no" when the question is about this company or its stock but nothing above bears on it; "off" when the question is not about this company's stock at all.
2. Then the answer: at most {MAX_SENTENCES} short sentences, plain words, for someone new to investing.
3. Never type a number. No digits, no currency signs, no percent signs, no number words (one, two ... twenty, twice, double, triple, half, a quarter of, dozen). Every quantity, date, price, percentage or count is written as its placeholder, exactly {{fact:id}}, and the system will insert the value. Describe time windows in words ("the next session", "the trailing month") rather than with numbers.
3a. A fact's "as of" date is not a fact: cite a date only through a fact whose value is that date. Each placeholder expands to the quoted "reads" phrase when one is given (otherwise to the bare value), so write the sentence around that phrase: "{{fact:quote}}, {{fact:distance_below_52_week_high}}" becomes "<price>, <share> below its 52-week high". Do not repeat words the phrase already carries.
4. State a comparison (more than usual, below its 52-week high, elevated, beat the estimate, confirmed, declared, after the close) only when a [word] fact above says exactly that.
5. COVERED: off: write no answer text; the system shows a fixed sentence. COVERED: no: say plainly in the first sentence that this page's data does not cover it, then what the facts do hold that is closest, with placeholders. Partly: say what they show and what they do not.
6. Never give a recommendation, a target, or an opinion about value; describe what the data shows and the idea behind it. Never call the stock cheap, expensive, undervalued or overvalued; a P/E is compared with the company's own history and its sector, nothing more.
6a. A placeholder's phrase is a complete clause ending: follow it with punctuation or a conjunction, never with more words about the same quantity ("{{fact:sessions_below_today_s_p_e}}." not "{{fact:sessions_below_today_s_p_e}} of the sessions tracked"). Do not repeat words a placeholder's phrase already carries: "{{fact:beats_followed_by_a_fall}}" reads "<count> of its last <count> beats", so write "fell after {{fact:beats_followed_by_a_fall}}". A move placeholder reads "a <signed percentage> move", so write "the stock had {{fact:1_day_move}} the next session", never "rose {{fact:1_day_move}}".
7. No greetings, no preamble, no bullet points, no markdown, no hedging about being an AI.

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


def sentences(text_: str) -> list[str]:
    return [s for s in SENTENCE_END.split(text_.strip()) if s]


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
        f = by_id[m.group(1)]
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
    facts = "\n".join(f"- {f['name']}: {f['value']}" + (f" (as of {f['as_of']})" if f["as_of"] else "") for f in pack["facts"])
    return f"""You are a rigorous fact-checker. Check each sentence of the answer below against the stored facts ONLY.

STORED FACTS about {pack['name']} ({pack['symbol']}):
{facts or '(none)'}

ANSWER:
{rendered}

RULES
- "supported": every factual claim in the sentence is confirmed by the facts, or the sentence states that the facts do not cover something and indeed no fact covers it, or the sentence explains an idea in general terms with no factual claim about this company.
- "unsupported": the sentence makes a claim about this company or its stock that the facts do not confirm (outside knowledge, an inference not in the facts).
- "contradicted": the sentence conflicts with a fact.
- Bias toward "unsupported" when in doubt. Use no outside knowledge.

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
    return hashlib.sha256(f"{symbol}|{normalized}|{fp}".encode()).hexdigest()[:32]


async def cached_answer(db: AsyncSession, key: str) -> dict | None:
    row = (await db.execute(text("SELECT answer FROM ask_log WHERE cache_key = :k AND answer IS NOT NULL AND verdict IN ('verified', 'partly_dropped', 'not_covered', 'off_topic') "
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
    await db.commit()


# ── the answer ───────────────────────────────────────────────────────────────

RULE = ("Ivy wrote the words from this stock's stored facts and typed no number: every quantity was inserted from a stored fact with its receipt, "
        "every comparison word was checked against a stored comparison, and each sentence was checked against those facts before display; "
        "a sentence the check did not support was dropped.")


def not_covered_answer(pack: dict, question: str) -> dict:
    return {"key": "ask", "question": question, "data": f"This page's stored data for {pack['name']} doesn't cover that question.", "idea": "", "inputs": [],
            "as_of": None, "as_of_kind": "observed", "rule": RULE}


def unchecked_answer(pack: dict, question: str) -> dict:
    """What a visitor sees when no draft passed the checks: a plain sentence, no guess."""
    return {"key": "ask", "question": question, "data": f"Ivy couldn't produce an answer about {pack['name']} that passed the checks for that question.", "idea": "",
            "inputs": [], "as_of": None, "as_of_kind": "observed", "rule": RULE}


def answer_payload(question: str, kept: list[str], inputs: list[dict], pack: dict) -> dict:
    as_of = max((i["as_of"] for i in inputs if i.get("as_of") and len(i["as_of"]) >= 10), default=None)
    today = date.today().isoformat()
    return {"key": "ask", "question": question, "data": " ".join(kept), "idea": "", "inputs": inputs,
            "as_of": (as_of[:10] if as_of and as_of[:10] <= today else None), "as_of_kind": "observed", "rule": RULE}


async def answer_question(db: AsyncSession, pack: dict, question: str, *, client=None) -> dict:
    """Run the model, the output check, the comparison check, substitution and the verifier for one question against a fact pack.
    Returns {verdict, covered, answer, model, input_tokens, output_tokens, cost, problems, dropped, raw}. Charges and logs nothing."""
    from app.services.anthropic_client import AnthropicClient
    client = client or AnthropicClient()
    prompt = build_prompt(pack, question)
    gen = await client.generate_answer(prompt)
    covered, body = parse_model_output(gen["content"])
    body = absorb_literals(body, pack["facts"])
    tokens = {"input_tokens": gen["input_tokens"], "output_tokens": gen["output_tokens"]}
    cost = estimate_cost_usd(gen["model_used"], gen["input_tokens"], gen["output_tokens"]) or 0.0
    out = {"covered": covered, "model": gen["model_used"], "raw": gen["content"], **tokens, "problems": [], "dropped": [], "retried": False}
    def all_problems(text_: str) -> list[str]:
        rendered_, _ = render(text_, pack["facts"])
        reps = [r for r in (repeated_phrase(sn) for sn in sentences(rendered_)) if r]
        return (check_output(text_, {f["id"] for f in pack["facts"]}, {f["id"] for f in pack["facts"] if f["kind"] == "note"}) + verify_comparisons(text_, pack["facts"])
                + [f'a sentence repeats the phrase "{r}"' for r in reps])
    problems = all_problems(body)
    if problems:
        # one rewrite with the check's reasons; a draft that fails twice is never shown
        gen2 = await client.generate_answer(prompt + "\n\nYour previous draft was rejected for these reasons: " + "; ".join(problems)
                                            + ". Rewrite it so none applies (spell no number word; use placeholders; state only comparisons a [word] fact gives; "
                                            "do not repeat words a placeholder's phrase already carries).\n\nAnswer:")
        covered, body = parse_model_output(gen2["content"])
        body = absorb_literals(body, pack["facts"])
        out.update(covered=covered, raw=gen2["content"], retried=True, first_problems=problems)
        out["input_tokens"] += gen2["input_tokens"]; out["output_tokens"] += gen2["output_tokens"]
        cost += estimate_cost_usd(gen2["model_used"], gen2["input_tokens"], gen2["output_tokens"]) or 0.0
        problems = all_problems(body)
    if problems:
        return {**out, "verdict": "rejected", "answer": unchecked_answer(pack, question), "problems": problems, "cost": cost}
    if covered == "off":
        return {**out, "verdict": "off_topic", "answer": fixed_answer("off_topic", pack, question), "cost": cost}
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
    if not kept:
        return {**out, "verdict": "rejected", "answer": unchecked_answer(pack, question), "dropped": dropped, "cost": cost + vcost, "problems": ["no sentence survived verification"]}
    used_inputs = [i for i in inputs if i["value"] in " ".join(kept)]
    return {**out, "verdict": "verified" if not dropped else "partly_dropped", "answer": answer_payload(question, kept, used_inputs, pack), "dropped": dropped, "cost": cost + vcost,
            "verifier": verdicts}


def ip_hash(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:12]
