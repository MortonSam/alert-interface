"""The model's part of Ivy's walkthrough: at most one story sentence for steps 1 to 3, one plain line on what the company does (the
summary's first line), up to three plain sentences for the risks the company names in Item 1A (step 7), and one sentence for each
Compare pair. Every number on screen is rule-built elsewhere
(services/walkthrough); these sentences carry none: a digit, a currency or percent sign or a number word fails the output check
(ask_ivy.check_output, which also rejects recommendation language, valuation verdicts and unexplained terms).

Each draft is then checked by the research-note verifier's model (anthropic_client.verify_walkthrough) against the fact pack and
the filing text it rests on (the company description, the step's figures, the risk factors' headings and text). A sentence that
fails either check is sent back once with its reasons; the rewrite is checked again and dropped if it fails. Nothing unverified
is stored. Calls are bounded (MODEL_SECONDS per attempt, one retry, CALL_SECONDS overall) and the night stops at
NIGHTLY_STORY_CAP_USD; stocks left over keep no story until the next run.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date

from app.services.research_cost import estimate_cost_usd

STORY_VERSION = 11                     # 5 (2026-10-19): no "sensitive to", "exposed to" or what may happen next outside step 7; no answer to a step's check; "does"
                                       # 6 (same day): step 1's story never sizes its lines; no "doubled"; no comparison with companies the evidence doesn't name
                                       # 7 (same day): no "whether", "keeps climbing" or "holding up" outside step 7
                                       # 8 (same day): "revenue", never "sales", for banks and insurers; "does" says what it sells or makes, never slogans;
                                       #   step 2's story never says how much profit each sale earns (its check's answer); the opening of the 10-K's Item 1 as evidence
                                       # 9 (same day): a step's story states only facts that step shows, on screen or in its Go deeper rows (the Compare
                                       #   rule): the description, Item 1 and other steps are evidence for "does" alone (step_problems, the verifier's rule)
                                       # 10 (same day): two kinds of step sentence. "company" states something about this company from its step's facts
                                       #   only (version 9's rule); "term" explains in general what a term or product shown on the step is or does, with no
                                       #   figure, cause or forecast, verified against Item 1 of the 10-K on step 1 and the step's facts plus general
                                       #   definitions on steps 2 and 3 (term_problems, the verifier's rule)
                                       # 11 (2026-10-20): a term sentence never defines the concept its step's idea box explains (IDEA_TERMS:
                                       #   segments, growth and earnings per share, margins); only a term the box doesn't cover
SPECULATION = re.compile(r"\b(?:likely|probably|perhaps|presumably|suggests? that|appears? to|seems? to|because|due to|thanks to|driven by|reflect\w*|result of|owing to|information (?:shown|here|given)|"
                         r"not (?:described|stated|shown|mentioned)|shown here|the (?:evidence|facts)|the data(?!\s+cent)|tends? to|(?:is|are|isn't|not|no) available|no description|not been (?:described|stated|shown)|described here|a fraction)\b", re.I)
# Sam's rule (2026-10-19): no model sentence says what the company is sensitive or exposed to, and only step 7 names risks or what
# may happen next (and only the company's own, from its Item 1A)
EXPOSURE = re.compile(r"\b(?:sensitive|sensitivity|exposed|exposure|vulnerab\w*)\b", re.I)
OUTLOOK = re.compile(r"\b(?:may|might|could|can|will|would|should|going forward|in the future|future|next|ahead|reverse|reversal|risks?|risky|warns?|threat\w*|"
                     r"uncertain\w*|momentum|lasts?|sustain\w*|outlook|whether|keeps? (?:climbing|rising|growing|falling)|holding up)\b", re.I)
# a step's story never states the reading its quick check asks for (walkthrough_checks)
GIVEAWAY = {"business": re.compile(r"\b(?:depend\w*|reli\w*|concentrat\w*|diversif\w*|single|one line|two lines|several lines|most|mostly|bulk|majority|"
                                  r"nearly all|remainder|rest|share|main|mainly|primar\w*|dominat\w*|largest|biggest|smaller|larger)\b", re.I),
            "growth": re.compile(r"\b(?:faster|slower|outpac\w*|outgr\w*|accelerat\w*|decelerat\w*|speed\w*|slow\w*|lag\w*|kept pace|in step|"
                                 r"each (?:sale|dollar)|per sale|(?:more|less) profit|profitab\w*)\b", re.I),
            "margins": re.compile(r"\b(?:pricing power|competition|competitive|costs? (?:fell|rose|dropped|climbed)|lower costs|rising costs|swing|swung|cycl\w*|volatil\w*|steady|stable|barely)\b", re.I)}
# Sam's rule (2026-10-19, MU step 2 "with the data center market now making up the bulk of revenue"): a step's story states only what
# that step shows. step_problems rejects a share of the business, a market or customer group, or a named line the step doesn't show.
SHARE_WORDS = re.compile(r"\b(?:mak(?:es?|ing) up|accounts? for|accounting for|bulk|majority|most of|share of|portion of)\b", re.I)
MARKET_WORDS = re.compile(r"\b(?:data cent(?:er|re)s?|cloud|artificial intelligence|AI|automotive|cars?|mobile|smartphones?|phones?|PCs?|personal computers?|"
                          r"gaming|consumers?|enterprises?|businesses|governments?|hyperscal\w*|industrial|servers?|networking|devices?|customers?|clients?|"
                          r"tenants?|retail|wholesale|international|overseas|abroad|China|Europe|Asia)\b", re.I)
SALES_WORD = re.compile(r"\bsales?\b", re.I)                                  # a bank or an insurer has revenue, never sales
# a "term" sentence explains, it never argues: no cause, and nothing about this company (its name or "the company")
CAUSE_WORDS = re.compile(r"(?<![\w-])(?:because|since|so|therefore|thus|hence|leads? to|led to|caus\w*|boost\w*|hurts?|explains? why)(?![\w-])", re.I)
COMPANY_WORDS = re.compile(r"\b(?:the company|this company|the firm|this firm|the business|its (?:sales|revenue|profits?|earnings|margins?|customers|results))\b", re.I)
STEP_KINDS = ("company", "term")
# Sam's rule (2026-10-20): a term sentence never defines what its step's "The idea" box already explains (walkthrough.IDEAS: segments
# on step 1, growth and earnings per share on step 2, margins on step 3); it is only for a term the box doesn't cover (DRAM, NAND, Compute)
IDEA_TERMS = {
    "business": re.compile(r"\b(?:segments?|10-K|annual report)\b", re.I),
    "growth": re.compile(r"\b(?:growth|grow\w*|year[- ]over[- ]year|same quarter|seasonal\w*|earnings per share|EPS)\b", re.I),
    "margins": re.compile(r"\b(?:margins?|gross profit|profit margin|slice)\b", re.I),
}
TERM_ROLES = re.compile(r"(?:customers?|clients?|tenants?|consumers?|devices?|businesses)", re.I)
MULTIPLES = re.compile(r"\b(?:doubl\w*|tripl\w*|quadrupl\w*|halv\w*|tenfold|\w+fold)\b", re.I)    # a figure in words
MODEL_SECONDS = 60
CALL_SECONDS = 150
NIGHTLY_STORY_CAP_USD = 8.0
STORY_WORDS = 32
RISK_WORDS = 28
MAX_RISKS = 3
RISKS_SHOWN_TO_MODEL = 12
BODY_TO_MODEL = 700
STORY_STEPS = ("business", "growth", "margins")
SUMMARY_KEYS = ("does",)               # the summary's plain line on what the company does (never on a step screen)

VOICE = """You are Ivy, explaining a company to someone who has never heard of it. Plain words, short sentences, no jargon, no hype.
Never recommend buying or selling, never call a stock cheap, expensive, a bargain or overvalued, never predict the price.
State only what the evidence says. Never guess at a cause, never generalise about an industry, never use "likely", "probably",
"suggests", "because", "due to" or "driven by" unless the risk factor text itself gives that cause, and never talk about the
information you were given or what it lacks. Never say what the company is sensitive to or exposed to. Outside the risks, never
name a risk or say what may, could or will happen next: describe what is, not what might be."""


def _client():
    from app.services.anthropic_client import AnthropicClient
    return AnthropicClient(timeout=MODEL_SECONDS, max_retries=1)


def step_lines(facts: dict, key: str) -> list[str]:
    """What one step shows: its figures, its sentences and its Go deeper rows, each tagged [key]."""
    st = (facts.get("steps") or {}).get(key)
    if not st:
        return []
    return ([f"[{key}] {n['label']}: {n['value']} ({n['as_of']})" for n in st["numbers"]] + [f"[{key}] {x}" for x in st["sentences"]]
            + [f"[{key}] Go deeper, {d['label']}: {d['value']}" + (f" ({d['as_of']})" if d.get("as_of") else "") for d in st.get("deeper") or []])


def fact_lines(facts: dict) -> list[str]:
    lines = []
    if facts.get("industry"):
        lines.append(f"[does] Sub-industry: {facts['industry']}")
    if facts.get("description"):
        lines.append(f"[does] Company description: {facts['description']}")
    if facts.get("business"):
        lines.append(f"[does] [business term] From Item 1, Business, of its 10-K: {facts['business']}")
    for key in (facts.get("steps") or {}):
        lines += step_lines(facts, key)
    return lines


def step_problems(key: str, sentence: str, facts: dict, kind: dict | None = None) -> list[str]:
    """Pure: a step's story naming what that step doesn't show (a share of the business, a market or customer group, a named line),
    though the description, Item 1 or another step may hold it. Only steps' stories: "does" and the risks have their own evidence.
    kind {"kind": "term", "term": ...} is a general explanation of a term the step shows: term_problems instead."""
    if key not in STORY_STEPS:
        return []
    if (kind or {}).get("kind") == "term":
        return term_problems(key, sentence, facts, kind.get("term") or "")
    own = " ".join(step_lines(facts, key))
    out = []
    for rx, what in ((SHARE_WORDS, "a share of the business"), (MARKET_WORDS, "a market or customer group")):
        for m in rx.finditer(sentence):
            if not re.search(rf"\b{re.escape(m.group(0))}\b", own, re.I):
                out.append(f"states {what} this step doesn't show: {m.group(0)}")
                break
    lines_named = {d["label"] for d in ((facts.get("steps") or {}).get("business") or {}).get("deeper") or []}
    for label in sorted(lines_named):
        words = [w for w in re.findall(r"[A-Za-z][\w&-]+", label) if w.lower() not in GENERIC_LINE_WORDS]
        if words and all(re.search(rf"\b{re.escape(w)}\b", sentence, re.I) for w in words) and not all(re.search(rf"\b{re.escape(w)}\b", own, re.I) for w in words):
            out.append(f"names a line this step doesn't show: {label}")
    return out


def _has(word: str, text: str) -> bool:
    return bool(re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.I))


def term_problems(key: str, sentence: str, facts: dict, term: str) -> list[str]:
    """Pure: a "term" sentence (Sam's case b, 2026-10-19) explains in general terms what a term or product shown on its step is or
    does. The term must be in the step's own lines and in the sentence; the sentence states no share, no cause and nothing about this
    company (a figure or a forecast already fails output_problems). A market or customer word must be in the step's lines or, on step 1,
    in the Item 1 text the verifier checks it against. Step 1 needs that Item 1 text to be verified at all."""
    term = " ".join(term.split())
    own = " ".join(step_lines(facts, key))
    out = []
    if not term:
        out.append("a term sentence names no term")
    elif not _has(term, own):
        out.append(f"explains a term this step doesn't show: {term}")
    elif not _has(term, sentence):
        out.append(f"does not name the term it explains: {term}")
    if key == "business" and not facts.get("business"):
        out.append("a term sentence on step 1 with no Item 1 text to check it against")
    m = IDEA_TERMS[key].search(term) if term and key in IDEA_TERMS else None
    if m:
        out.append(f"defines what the step's idea box already explains: {m.group(0)}")
    m = SHARE_WORDS.search(sentence)
    if m:
        out.append(f"states a share of the business: {m.group(0)}")
    m = CAUSE_WORDS.search(sentence)
    if m:
        out.append(f"a term sentence states a cause: {m.group(0)}")
    first = (facts.get("name") or "").split()[0] if facts.get("name") else ""
    m = COMPANY_WORDS.search(sentence)
    if (first and _has(first, sentence)) or m:
        out.append(f"a term sentence states something about this company: {m.group(0) if m else first}")
    allowed = own + (" " + (facts.get("business") or "") if key == "business" else "")
    for m in MARKET_WORDS.finditer(sentence):
        if TERM_ROLES.fullmatch(m.group(0)):
            continue                                    # a definition's generic party ("a customer pays to use a vehicle") is no market
        if not _has(m.group(0), allowed) and not _has(m.group(0), term):
            out.append(f"names a market or customer group its evidence doesn't show: {m.group(0)}")
            break
    return out


GENERIC_LINE_WORDS = {"products", "product", "services", "service", "segment", "business", "unit", "other", "and", "the", "of", "total",
                      "company", "description", "group", "solutions", "revenue", "sales"}


def risk_lines(facts: dict, limit: int = RISKS_SHOWN_TO_MODEL, body: int = BODY_TO_MODEL, only: set[int] | None = None) -> list[str]:
    out = []
    for r in (facts.get("risks") or [])[:limit] if only is None else [r for r in facts.get("risks") or [] if r["n"] in only]:
        out.append(f"RISK {r['n']}: {r['heading']}\n   {r['body'][:body]}")
    return out


def build_prompt(facts: dict, redo: dict | None = None) -> str:
    steps = [k for k in STORY_STEPS if k in (facts.get("steps") or {})]
    want = {k: "one sentence" for k in steps}
    if facts.get("description") or "business" in (facts.get("steps") or {}):
        want["does"] = "one sentence"
    if facts.get("risks"):
        want["risks"] = f"up to {MAX_RISKS} items"
    if redo:
        want = {k: v for k, v in want.items() if k in redo}
    shape = ", ".join(f'"{k}": ' + ('[{"n": <risk number>, "sentence": "..."}]' if k == "risks" else
                                     '{"kind": "company" or "term", "term": "<only for kind term, the term exactly as the step shows it>", "sentence": "..."}'
                                     if k in STORY_STEPS else '"..."') for k in want)
    redo_block = ""
    if redo:
        redo_block = "\nYOUR LAST DRAFT FAILED THESE CHECKS. Write each again so it passes:\n" + "\n".join(f"- {k}: {v}" for k, v in redo.items()) + "\n"
    revenue_rule = ("\n- This company is a bank or an insurer: call what it brings in \"revenue\", never \"sales\"." if facts.get("noun") == "revenue" else "")
    return f"""{VOICE}

COMPANY: {facts['name']} ({facts.get('sector') or 'sector not on file'})

FACTS ALREADY ON SCREEN (the reader sees these figures above your sentence):
{chr(10).join(fact_lines(facts)) or '(none)'}

RISK FACTORS FROM ITEM 1A OF ITS 10-K (filed {facts.get('risk_filed') or 'n/a'}):
{chr(10).join(risk_lines(facts)) or '(none)'}
{redo_block}
WRITE
- For each of {', '.join(k for k in want if k not in ('risks', 'does')) or 'no step'}: ONE sentence of at most {STORY_WORDS} words that helps a newcomer, of one of two kinds.
  kind "company": it states something about this company (a figure's meaning, a trend, a comparison), using only facts in that step's
  own [step] lines (its figures, its sentences and its Go deeper rows). A fact that is only in the [does] lines, another step's lines
  or the risk factors may not appear in it, however true: no market, customer group, product line or share of the business that step
  doesn't show. It adds meaning, it does not repeat the figures.
  kind "term": it explains in general terms what a term or product named in that step's own lines is or does (for example, what DRAM
  is, or what gross margin measures), and says nothing about this company: not its name, its figures, its customers or its results.
  The term must appear word for word in that step's own [step] lines (a line name, a measure, a label), never one found only in the
  [does] or [business term] lines: give it exactly as the step's lines show it, and use it in the sentence. The page already explains
  segments on "business", growth and earnings per share on "growth" and margins on "margins": never explain those or a kind of them
  (gross margin, profit margin, sales growth); explain only a term or product the step shows beyond them (a product line, a segment's name). On "business" the explanation must be true to the
  [business term] Item 1 text; on "growth" and "margins" it must be a standard definition. No figure, no cause, no forecast.
  Either kind describes what is: no risks, nothing the company is sensitive or exposed to, nothing about what may happen next.
  For "growth", never compare how fast two figures grew. For "business", a term sentence may say what its biggest line is or does in plain words, never how
  big any line is or how much the company depends on it (no most, bulk, majority, share, main).
  For "margins", never say what the change in its margin points to (pricing, costs, competition) or call it a swing or a cycle.
- For "does": ONE sentence of at most {STORY_WORDS} words saying in plain words what the company does, what it sells or makes and to
  whom, using only the [does] and [business] lines above (begin with the company's name). No marketing words, no slogans, nothing about
  the index it belongs to or how it describes itself.{revenue_rule}
- For "risks": choose up to {MAX_RISKS} of the risk factors that matter most for understanding this business, and say each in ONE plain sentence of
  at most {RISK_WORDS} words, true to its heading and text, with no detail that is not in them.
- No digits, no currency or percent signs, no number words (one, two, ten, twice, double, half, dozen). No dates. No colons, semicolons or dashes.
  For size, use plain words: most, the bulk, a large share, a small share, a majority, sharply, steadily. If a sentence cannot be
  written well without a number, write about what the figure means instead.
- Never mention Ivy, this page, the chart, the data or your sources.

Return JSON only: {{{shape}}}"""


def parse_draft(content: str) -> dict:
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    out: dict = {}
    kinds = {}
    for k in STORY_STEPS + SUMMARY_KEYS:
        v = d.get(k)
        if k in STORY_STEPS and isinstance(v, dict):
            if isinstance(v.get("sentence"), str) and v["sentence"].strip() and v.get("kind") in STEP_KINDS:
                out[k] = " ".join(v["sentence"].split())
                kinds[k] = {"kind": v["kind"], "term": " ".join(str(v.get("term") or "").split())} if v["kind"] == "term" else {"kind": "company"}
        elif isinstance(v, str) and v.strip():
            out[k] = " ".join(v.split())
            if k in STORY_STEPS:
                kinds[k] = {"kind": "company"}
    if kinds:
        out["kinds"] = kinds
    risks = []
    for r in d.get("risks") or []:
        if isinstance(r, dict) and isinstance(r.get("sentence"), str) and str(r.get("n", "")).isdigit():
            risks.append({"n": int(r["n"]), "sentence": " ".join(r["sentence"].split())})
    if risks:
        out["risks"] = risks[:MAX_RISKS]
    return out


def output_problems(sentence: str, words: int, key: str | None = None, noun: str = "sales") -> list[str]:
    """Pure: why a drafted sentence cannot be shown (ask_ivy.check_output with no facts allowed, plus length and punctuation, plus
    Sam's rule: nothing sensitive or exposed anywhere, and outside the risks (key "risk:N") no risk and nothing about what may
    happen next; a step's sentence never states its check's answer)."""
    from app.services.ask_ivy import check_output, sentences
    problems = check_output(sentence, set())
    if len(sentences(sentence)) != 1:
        problems.append("not exactly one sentence")
    if not sentence.rstrip().endswith((".", "!", "?")):
        problems.append("does not end with a full stop")
    if len(sentence.split()) > words:
        problems.append(f"over {words} words")
    if re.search(r"[:;—–]", sentence):
        problems.append("a colon, semicolon or dash")
    m = SPECULATION.search(sentence)
    if m:
        problems.append(f"speculation, a stated cause or talk about the information: {m.group(0)}")
    m = MULTIPLES.search(sentence)
    if m:
        problems.append(f"a figure in words: {m.group(0)}")
    m = EXPOSURE.search(sentence)
    if m:
        problems.append(f"says what the company is sensitive or exposed to: {m.group(0)}")
    if not (key or "").startswith("risk:"):
        m = OUTLOOK.search(sentence)
        if m:
            problems.append(f"names a risk or what may happen next, which only the risks may: {m.group(0)}")
    if noun == "revenue" and SALES_WORD.search(sentence):
        problems.append("says sales for a bank or an insurer, which has revenue")
    if key in GIVEAWAY:
        m = GIVEAWAY[key].search(sentence)
        if m:
            problems.append(f"states the reading the step's quick check asks for: {m.group(0)}")
    return problems


def items(draft: dict, risk_ns: set[int]) -> list[tuple[str, str]]:
    """Pure: [(id, sentence)] in a fixed order: steps, then risk:<n> for risks the filing has (an unknown number is dropped)."""
    out = [(k, draft[k]) for k in STORY_STEPS + SUMMARY_KEYS if k in draft]
    seen = set()
    for r in draft.get("risks", []):
        if r["n"] in risk_ns and r["n"] not in seen:
            seen.add(r["n"])
            out.append((f"risk:{r['n']}", r["sentence"]))
    return out


def verification_prompt(facts: dict, drafted: list[tuple[str, str]], kinds: dict | None = None) -> str:
    chosen = {int(i.split(":")[1]) for i, _ in drafted if i.startswith("risk:")}
    kinds = kinds or {}

    def label(i: str) -> str:
        k = kinds.get(i) or {}
        return f'{i} [explains the term "{k.get("term")}"]' if k.get("kind") == "term" else i
    return f"""You are a rigorous fact-checker. Check each sentence below against the evidence ONLY. Use no outside knowledge, except the one
case the rules allow (a standard definition of a term on growth or margins).

EVIDENCE 1, FIGURES AND THE COMPANY DESCRIPTION for {facts['name']}:
{chr(10).join(fact_lines(facts)) or '(none)'}

EVIDENCE 2, RISK FACTORS FROM ITEM 1A OF ITS 10-K:
{chr(10).join(risk_lines(facts, body=1500, only=chosen)) or '(none)'}

SENTENCES:
{chr(10).join(f'{label(i)}: {s}' for i, s in drafted)}

RULES
- "supported": every factual claim is confirmed by the evidence. A sentence with id risk:N must be true to RISK N's heading and text. A general
  explanation of an idea with no claim about this company is supported. A clause saying why a confirmed fact matters does not make it unsupported.
- A sentence whose id is not risk:N is "unsupported" if it says what the company is sensitive or exposed to, names a risk, or says what
  may, could or will happen next. Only risk:N sentences may name risks, and only the company's own.
- A "does" sentence must say only what the company does, sells or makes, as the evidence states it.
- A sentence whose id is business, growth or margins (with no term named) states something about this company and may state only facts
  in that step's own lines (tagged [business], [growth] or [margins]: its figures, its sentences and its Go deeper rows). A claim found
  only in the [does] lines, another step's lines or the risk factors is "unsupported" for it, however true (a market, a customer group,
  a product line, a share of the business).
- A sentence marked [explains the term "..."] explains in general terms what that term is or does. It is "unsupported" if the term is
  not in that step's own lines, if it explains segments, growth, earnings per share or a margin (the page explains those already), if it states a figure, a cause or a forecast, or if it says anything about this company. On business,
  the explanation must be confirmed by the [business term] line (Item 1 of its 10-K). On growth or margins, it must be confirmed by that
  step's own lines or be a standard, widely used definition of the term (the only outside knowledge allowed).
- A comparison with other companies or an industry ("few companies match", "unlike its peers") is "unsupported" unless the evidence names them.
- "unsupported": it claims something about this company the evidence does not confirm.
- "contradicted": it conflicts with the evidence.
- Bias toward "unsupported" when in doubt.

Return JSON only, each id exactly as given before any [ ] mark: {{"verdicts": [{{"id": "...", "status": "supported|unsupported|contradicted", "reason": "one sentence"}}]}}"""


def parse_verdicts(content: str) -> dict[str, dict]:
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        rows = json.loads(m.group(0)).get("verdicts") or [] if m else []
    except ValueError:
        rows = []
    # the id alone: a verifier that echoes a term mark ('business [explains the term "DRAM"]') still matches
    return {re.split(r"[\s\[(]", str(r.get("id")).strip(), maxsplit=1)[0]: {"status": r.get("status"), "reason": r.get("reason")} for r in rows if isinstance(r, dict)}


async def _call(fn, prompt: str) -> tuple[str, float | None]:
    out = await asyncio.wait_for(fn(prompt), CALL_SECONDS)
    return out["content"], estimate_cost_usd(out["model_used"], out["input_tokens"], out["output_tokens"])


async def story_for(facts: dict, *, client=None) -> dict:
    """{sentences: {id: sentence}, verdicts: {id: {status, reason, round}}, dropped: [...], cost_usd}. Two rounds at most."""
    if not any(k in (facts.get("steps") or {}) for k in STORY_STEPS) and not facts.get("risks"):
        return {"version": STORY_VERSION, "sentences": {}, "verdicts": {}, "dropped": [], "cost_usd": 0.0}     # nothing to write about: no call
    client = client or _client()
    risk_ns = {r["n"] for r in facts.get("risks") or []}
    kept: dict[str, str] = {}
    verdicts: dict[str, dict] = {}
    dropped: list[dict] = []
    cost = 0.0
    redo: dict | None = None
    kinds: dict = {}
    for rnd in (1, 2):
        content, c = await _call(lambda p: client.generate_walkthrough(p, max_tokens=900), build_prompt(facts, redo))
        cost += c or 0.0
        draft = parse_draft(content)
        kinds = {**kinds, **draft.get("kinds", {})} if rnd == 2 else draft.get("kinds", {})
        drafted = [(i, s) for i, s in items(draft, risk_ns) if i not in kept]
        if rnd == 2:
            drafted = [(i, s) for i, s in drafted if (i if not i.startswith("risk:") else "risks") in (redo or {})]
        failed: dict[str, str] = {}
        clean = []
        for i, s in drafted:
            p = output_problems(s, RISK_WORDS if i.startswith("risk:") else STORY_WORDS, i, facts.get("noun") or "sales") + step_problems(i, s, facts, kinds.get(i))
            if p:
                failed[i] = "; ".join(p)
                verdicts[i] = {"status": "rejected", "reason": failed[i], "round": rnd, "draft": s, **kinds.get(i, {})}
            else:
                clean.append((i, s))
        if clean:
            vcontent, vc = await _call(client.verify_walkthrough, verification_prompt(facts, clean, kinds))
            cost += vc or 0.0
            vs = parse_verdicts(vcontent)
            for i, s in clean:
                v = vs.get(i) or {"status": "unsupported", "reason": "no verdict returned"}
                verdicts[i] = {**v, "round": rnd, "draft": s, **kinds.get(i, {})}
                if v.get("status") == "supported":
                    kept[i] = s
                else:
                    failed[i] = v.get("reason") or v.get("status") or "not supported"
        if not failed or rnd == 2:
            dropped += [{"id": i, "reason": r} for i, r in failed.items()]
            break
        redo = {}
        for i, r in failed.items():
            key = "risks" if i.startswith("risk:") else i
            redo[key] = (redo.get(key, "") + f" {i}: {r}").strip()
    extra = [i for i in kept if i.startswith("risk:")][MAX_RISKS:]      # the rewrite round adds to the first round's risks: never more than MAX_RISKS
    for i in extra:
        kept.pop(i)
        dropped.append({"id": i, "reason": f"over the {MAX_RISKS} risks shown"})
    return {"version": STORY_VERSION, "sentences": kept, "verdicts": verdicts, "dropped": dropped, "cost_usd": round(cost, 4)}


def apply(payload: dict, story: dict, headings: dict[int, str] | None = None) -> None:
    """Pure (in place): the verified sentences onto the payload's steps. The "does" line replaces step 1's vendor description (when that
    is its first sentence) and leads the summary's step 1 line."""
    from app.services import walkthrough as W
    sents = (story or {}).get("sentences") or {}
    by_key = {s["key"]: s for s in payload["steps"]}
    for k in STORY_STEPS:
        if k in sents and by_key[k]["status"] != "absent":
            by_key[k]["story"] = sents[k]
    b = by_key["business"]
    if sents.get("does") and b["status"] != "absent":
        if b.get("described") and b["sentences"]:
            b["sentences"][0] = sents["does"]
        seg_line = b["summary"] if b.get("fact") else None          # with a sales split, its line follows; else the plain line replaces the description
        b["summary"] = sents["does"] + (f" {seg_line}" if seg_line else "")
    risks = [{"n": int(i.split(":")[1]), "sentence": s} for i, s in sents.items() if i.startswith("risk:")]
    st = by_key["risks"]
    if st["status"] != "absent":
        W.with_risk_story(st, payload["name"], sorted(risks, key=lambda r: r["n"]), headings, payload["steps"], payload.get("noun") or "sales")
    payload["summary"] = W.summary(payload["name"], payload["steps"])


def headings_of(b: dict) -> dict[int, str]:
    return {r["n"]: r["heading"] for r in (b.get("story_facts") or {}).get("risks") or []}


# ── Compare's sentence ─────────────────────────────────────────────────────────────────────────────────────────────────────

STORY_COMPARE_ROWS = ("sells", "growth", "keeps_now", "keeps_then")    # filing facts only: a price, a P/E or a date would change nightly and stale the sentence
COMPARE_STORY_VERSION = 2              # 2 (2026-10-19): a Compare sentence uses only the rows its table shows (row_problems, the verifier's rule)
# what a sentence about each row says; a row the table hides (or, for the price rows, never gives the model) may not be named
ROW_WORDS = {"sells": re.compile(r"\b(?:biggest|largest|main|single) (?:line|product|business|segment)|\bmost of its (?:sales|revenue)|\bshare of (?:its )?(?:sales|revenue)", re.I),
             "growth": re.compile(r"\b(?:gr[eo]w\w*|growth|faster|slower|expand\w*|shr[iu]nk\w*)\b", re.I),
             "keeps": re.compile(r"\b(?:margins?|keeps?|kept|profit\w*)\b|\beach (?:sales |revenue )?dollar", re.I),
             "price": re.compile(r"\b(?:stock|share price|valued|valuation|P/E|price to|dividends?|yield)\b", re.I)}


def slow_rows(a: dict, b: dict) -> list[dict]:
    from app.services.walkthrough import compare_table
    return [r for r in compare_table(a["compare"], b["compare"]) if r["key"] in STORY_COMPARE_ROWS]


def compare_fingerprint(a: dict, b: dict) -> str:
    from app.services import walkthrough as W
    return W.fingerprint({"v": STORY_VERSION, "cv": COMPARE_STORY_VERSION, "rows": slow_rows(a, b), "da": described(a), "db": described(b)})


def row_problems(sentence: str, shown: set[str]) -> list[str]:
    """Pure: a Compare sentence naming a row its table hides (shown: the keys of the rows given to the model)."""
    have = {"sells": "sells" in shown, "growth": "growth" in shown, "keeps": bool({"keeps_now", "keeps_then"} & shown), "price": False}
    out = []
    for k, rx in ROW_WORDS.items():
        m = rx.search(sentence)
        if m and not have[k]:
            out.append(f"names a row the table does not show: {m.group(0)}")
    return out


def compare_facts(a: dict, b: dict) -> list[str]:
    lines = []
    rows = slow_rows(a, b)
    for p, side in ((a, "a"), (b, "b")):
        for r in rows:
            v = r[side]
            if v:
                lines.append(f"{p['name']}, {r['label']}: {v['value']} ({v['as_of']})")
        desc = next((s["sentences"][0] for s in p["steps"] if s["key"] == "business" and s["status"] != "absent" and s["sentences"]), None)
        if desc:
            lines.append(f"{p['name']}, description: {desc}")
    return lines


def described(p: dict) -> bool:
    return any(s["key"] == "business" and s["status"] != "absent" for s in p["steps"])


def compare_prompt(a: dict, b: dict, redo: str | None = None) -> str:
    return f"""{VOICE}

Two companies side by side, {a['name']} and {b['name']}. The reader sees these figures:
{chr(10).join(compare_facts(a, b))}
{f"YOUR LAST DRAFT FAILED: {redo}" if redo else ""}
Write ONE sentence of at most {STORY_WORDS} words that tells a newcomer the most useful difference between the two businesses, using only the facts above.
Use only the rows listed above: say nothing about growth, margins, the biggest line, the stock, its price or its valuation unless that row is listed.
No digits, no currency or percent signs, no number words, no dates, no colons, semicolons or dashes. Return JSON only: {{"sentence": "..."}}"""


async def compare_story(a: dict, b: dict, *, client=None) -> dict:
    client = client or _client()
    cost, redo, verdicts = 0.0, None, []
    for rnd in (1, 2):
        content, c = await _call(lambda p: client.generate_walkthrough(p, max_tokens=200), compare_prompt(a, b, redo))
        cost += c or 0.0
        m = re.search(r"\{.*\}", content or "", re.S)
        try:
            s = " ".join(str(json.loads(m.group(0)).get("sentence") or "").split()) if m else ""
        except ValueError:
            s = ""
        problems = (output_problems(s, STORY_WORDS) + row_problems(s, {r["key"] for r in slow_rows(a, b)})) if s else ["no sentence"]
        if not problems:
            vcontent, vc = await _call(client.verify_walkthrough, f"""You are a rigorous fact-checker. Check the sentence against the evidence ONLY.
EVIDENCE:
{chr(10).join(compare_facts(a, b))}
SENTENCE: compare: {s}
A comparison is supported when the figures confirm it. The sentence may use only the rows listed in the evidence: a claim about growth, margins,
the biggest line, the stock, its price or its valuation is "unsupported" when the evidence lists no such row. Bias toward "unsupported" when in doubt.
Return JSON only: {{"verdicts": [{{"id": "compare", "status": "supported|unsupported|contradicted", "reason": "one sentence"}}]}}""")
            cost += vc or 0.0
            v = parse_verdicts(vcontent).get("compare") or {"status": "unsupported", "reason": "no verdict returned"}
            verdicts.append({**v, "round": rnd, "draft": s})
            if v.get("status") == "supported":
                return {"sentence": s, "verdicts": verdicts, "cost_usd": round(cost, 4)}
            redo = v.get("reason")
        else:
            verdicts.append({"status": "rejected", "reason": "; ".join(problems), "round": rnd, "draft": s})
            redo = "; ".join(problems)
    return {"sentence": None, "verdicts": verdicts, "cost_usd": round(cost, 4)}


# ── the nightly pass ───────────────────────────────────────────────────────────────────────────────────────────────────────

async def run_stories(built: dict, today: date, cap: float = NIGHTLY_STORY_CAP_USD) -> float:
    """For each built stock: reuse its stored story when the story facts are unchanged, else write a new one while the night's
    spend is under `cap`; then Compare's sentences for each stock against its rival and its ruler. Returns the spend."""
    from app.services import walkthrough as W
    from app.services.redact import redact
    spent = 0.0
    for sym, b in built.items():
        fp = W.fingerprint({"v": STORY_VERSION, "facts": b["story_facts"]})
        prior = b["prior"] or {}
        if prior.get("story_fingerprint") == fp and prior.get("story"):
            b["story"], b["story_fingerprint"] = prior["story"], fp
        elif spent < cap:
            try:
                st = await story_for(b["story_facts"])
                spent += st["cost_usd"]
                b["story"], b["story_fingerprint"] = {**st, "at": today.isoformat()}, fp
                print(f"  {sym}: story {len(st['sentences'])} kept, {len(st['dropped'])} dropped, ${st['cost_usd']:.3f}", flush=True)
            except Exception as exc:
                print(f"  {sym}: story failed: {redact(exc)[:120]}", flush=True)
                b["story"], b["story_fingerprint"] = {}, None
        else:
            b["story"], b["story_fingerprint"] = {}, None          # facts changed and the night's cap is spent: no stale story
        apply(b["payload"], b["story"], headings_of(b))
    return await compare_stories(built, spent, cap)


async def reuse_stories(built: dict) -> None:
    """Without model calls: each stock keeps its stored story only while its story facts are unchanged."""
    from app.services import walkthrough as W
    for b in built.values():
        fp = W.fingerprint({"v": STORY_VERSION, "facts": b["story_facts"]})
        prior = b["prior"] or {}
        ok = prior.get("story_fingerprint") == fp and prior.get("story")
        b["story"], b["story_fingerprint"] = (prior["story"], fp) if ok else ({}, None)
        apply(b["payload"], b["story"], headings_of(b))


async def compare_stories(built: dict, spent: float, cap: float) -> float:
    from sqlalchemy import text
    from app.database import ScriptSessionLocal
    from app.services import walkthrough as W
    from app.services.walkthrough_compare import rival_for, ruler_for
    from app.services.redact import redact
    async with ScriptSessionLocal() as db:
        tickers = {r.symbol: dict(r._mapping) for r in (await db.execute(text("SELECT symbol, sector, industry, market_cap, index_member FROM tickers WHERE is_active"))).all()}
        have = set(built) | set((await db.execute(text("SELECT symbol FROM ivy_walkthroughs"))).scalars().all())
        stored = {(r.symbol, r.other): r.fingerprint for r in (await db.execute(text("SELECT symbol, other, fingerprint FROM ivy_compare_stories"))).all()}
        payloads = {r.symbol: r.payload for r in (await db.execute(text("SELECT symbol, payload FROM ivy_walkthroughs"))).all()}
        payloads.update({s: b["payload"] for s, b in built.items()})
        for sym in built:
            rival = rival_for(sym, tickers, have)
            for other in [o for o in [(rival or {}).get("symbol"), ruler_for(sym)] if o and o in payloads and o != sym]:
                a, b = payloads[sym], payloads[other]
                fp = compare_fingerprint(a, b)
                if stored.get((sym, other)) == fp or spent >= cap:
                    continue
                try:
                    # a side with no step 1 has nothing true to contrast: no call, no sentence (VMRK 2026-10-19 drafted "no description is available")
                    st = (await compare_story(a, b)) if described(a) and described(b) else {"sentence": None, "verdicts": [{"status": "skipped", "reason": "a side has no step 1"}], "cost_usd": 0.0}
                except Exception as exc:
                    print(f"  {sym} vs {other}: compare sentence failed: {redact(exc)[:120]}", flush=True)
                    continue
                spent += st["cost_usd"]
                await db.execute(text("""INSERT INTO ivy_compare_stories (symbol, other, fingerprint, sentence, verdicts, cost_usd, built_at)
                    VALUES (:s, :o, :f, :t, CAST(:v AS jsonb), :c, now()) ON CONFLICT (symbol, other) DO UPDATE SET fingerprint = EXCLUDED.fingerprint,
                    sentence = EXCLUDED.sentence, verdicts = EXCLUDED.verdicts, cost_usd = EXCLUDED.cost_usd, built_at = now()"""),
                    {"s": sym, "o": other, "f": fp, "t": st["sentence"], "v": json.dumps(st["verdicts"]), "c": st["cost_usd"]})
                await db.commit()
                print(f"  {sym} vs {other}: {'kept' if st['sentence'] else 'dropped'}, ${st['cost_usd']:.3f}", flush=True)
    return spent
