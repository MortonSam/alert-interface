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

STORY_VERSION = 8                      # 5 (2026-10-19): no "sensitive to", "exposed to" or what may happen next outside step 7; no answer to a step's check; "does"
                                       # 6 (same day): step 1's story never sizes its lines; no "doubled"; no comparison with companies the evidence doesn't name
                                       # 7 (same day): no "whether", "keeps climbing" or "holding up" outside step 7
                                       # 8 (same day): "revenue", never "sales", for banks and insurers; "does" says what it sells or makes, never slogans;
                                       #   step 2's story never says how much profit each sale earns (its check's answer); the opening of the 10-K's Item 1 as evidence
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
SALES_WORD = re.compile(r"\bsales?\b", re.I)                                  # a bank or an insurer has revenue, never sales
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


def fact_lines(facts: dict) -> list[str]:
    lines = []
    if facts.get("industry"):
        lines.append(f"Sub-industry: {facts['industry']}")
    if facts.get("description"):
        lines.append(f"Company description: {facts['description']}")
    if facts.get("business"):
        lines.append(f"From Item 1, Business, of its 10-K: {facts['business']}")
    for key, st in (facts.get("steps") or {}).items():
        for n in st["numbers"]:
            lines.append(f"[{key}] {n['label']}: {n['value']} ({n['as_of']})")
        for s in st["sentences"]:
            lines.append(f"[{key}] {s}")
    return lines


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
    shape = ", ".join(f'"{k}": ' + ('[{"n": <risk number>, "sentence": "..."}]' if k == "risks" else '"..."') for k in want)
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
- For each of {', '.join(k for k in want if k not in ('risks', 'does')) or 'no step'}: ONE sentence of at most {STORY_WORDS} words that helps a newcomer see why the figures for that step matter
  for this company, using only the facts and the risk factors above. It adds meaning, it does not repeat the figures. It describes
  what is: no risks, nothing the company is sensitive or exposed to, nothing about what may happen next.
  For "growth", never compare how fast two figures grew. For "business", say what its biggest line is or does in plain words, never how
  big any line is or how much the company depends on it (no most, bulk, majority, share, main).
  For "margins", never say what the change in its margin points to (pricing, costs, competition) or call it a swing or a cycle.
- For "does": ONE sentence of at most {STORY_WORDS} words saying in plain words what the company does, what it sells or makes and to
  whom, using only the facts and the risk factors above (begin with the company's name). No marketing words, no slogans, nothing about
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
    for k in STORY_STEPS + SUMMARY_KEYS:
        if isinstance(d.get(k), str) and d[k].strip():
            out[k] = " ".join(d[k].split())
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


def verification_prompt(facts: dict, drafted: list[tuple[str, str]]) -> str:
    chosen = {int(i.split(":")[1]) for i, _ in drafted if i.startswith("risk:")}
    return f"""You are a rigorous fact-checker. Check each sentence below against the evidence ONLY. Use no outside knowledge.

EVIDENCE 1, FIGURES AND THE COMPANY DESCRIPTION for {facts['name']}:
{chr(10).join(fact_lines(facts)) or '(none)'}

EVIDENCE 2, RISK FACTORS FROM ITEM 1A OF ITS 10-K:
{chr(10).join(risk_lines(facts, body=1500, only=chosen)) or '(none)'}

SENTENCES:
{chr(10).join(f'{i}: {s}' for i, s in drafted)}

RULES
- "supported": every factual claim is confirmed by the evidence. A sentence with id risk:N must be true to RISK N's heading and text. A general
  explanation of an idea with no claim about this company is supported. A clause saying why a confirmed fact matters does not make it unsupported.
- A sentence whose id is not risk:N is "unsupported" if it says what the company is sensitive or exposed to, names a risk, or says what
  may, could or will happen next. Only risk:N sentences may name risks, and only the company's own.
- A "does" sentence must say only what the company does, sells or makes, as the evidence states it.
- A comparison with other companies or an industry ("few companies match", "unlike its peers") is "unsupported" unless the evidence names them.
- "unsupported": it claims something about this company the evidence does not confirm.
- "contradicted": it conflicts with the evidence.
- Bias toward "unsupported" when in doubt.

Return JSON only: {{"verdicts": [{{"id": "...", "status": "supported|unsupported|contradicted", "reason": "one sentence"}}]}}"""


def parse_verdicts(content: str) -> dict[str, dict]:
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        rows = json.loads(m.group(0)).get("verdicts") or [] if m else []
    except ValueError:
        rows = []
    return {str(r.get("id")): {"status": r.get("status"), "reason": r.get("reason")} for r in rows if isinstance(r, dict)}


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
    for rnd in (1, 2):
        content, c = await _call(lambda p: client.generate_walkthrough(p, max_tokens=900), build_prompt(facts, redo))
        cost += c or 0.0
        drafted = [(i, s) for i, s in items(parse_draft(content), risk_ns) if i not in kept]
        if rnd == 2:
            drafted = [(i, s) for i, s in drafted if (i if not i.startswith("risk:") else "risks") in (redo or {})]
        failed: dict[str, str] = {}
        clean = []
        for i, s in drafted:
            p = output_problems(s, RISK_WORDS if i.startswith("risk:") else STORY_WORDS, i, facts.get("noun") or "sales")
            if p:
                failed[i] = "; ".join(p)
                verdicts[i] = {"status": "rejected", "reason": failed[i], "round": rnd, "draft": s}
            else:
                clean.append((i, s))
        if clean:
            vcontent, vc = await _call(client.verify_walkthrough, verification_prompt(facts, clean))
            cost += vc or 0.0
            vs = parse_verdicts(vcontent)
            for i, s in clean:
                v = vs.get(i) or {"status": "unsupported", "reason": "no verdict returned"}
                verdicts[i] = {**v, "round": rnd, "draft": s}
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


def slow_rows(a: dict, b: dict) -> list[dict]:
    from app.services.walkthrough import compare_table
    return [r for r in compare_table(a["compare"], b["compare"]) if r["key"] in STORY_COMPARE_ROWS]


def compare_fingerprint(a: dict, b: dict) -> str:
    from app.services import walkthrough as W
    return W.fingerprint({"v": STORY_VERSION, "rows": slow_rows(a, b), "da": described(a), "db": described(b)})


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
        problems = output_problems(s, STORY_WORDS) if s else ["no sentence"]
        if not problems:
            vcontent, vc = await _call(client.verify_walkthrough, f"""You are a rigorous fact-checker. Check the sentence against the evidence ONLY.
EVIDENCE:
{chr(10).join(compare_facts(a, b))}
SENTENCE: compare: {s}
A comparison is supported when the figures confirm it. Bias toward "unsupported" when in doubt.
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
