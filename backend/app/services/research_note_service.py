"""Service layer for generating and verifying AI research notes."""

from __future__ import annotations
from app.services.redact import redact

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.basis_exclusion import basis_mismatch_dates, excluded_note
from app.services.price_history_exclusion import EXCLUSION_REASON, is_excluded
from app.database import AsyncSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.research_note import ResearchNote
from app.models.ticker import Ticker
from app.services.anthropic_client import AnthropicClient
from app.services.edgar_client import EdgarClient
from app.services.finnhub_client import FinnhubClient
from app.services import financials_cache


# ── Precomputed stats ─────────────────────────────────────────────────────────

def _pct(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _fmt_pct(v: float | None) -> str:
    return f"{v:+.2f}%" if v is not None else "N/A"


def _precompute_stats(reactions: list[HistoricalReaction]) -> dict:
    """Return a dict of authoritative, Python-computed statistics.

    Quarters _fetch_context marked basis_mismatch (EPS actual and estimate on
    different bases) leave every count; basis_excluded says how many.
    """
    basis_excluded = sum(1 for r in reactions if getattr(r, "basis_mismatch", False))
    reactions = [r for r in reactions if not getattr(r, "basis_mismatch", False)]
    total = len(reactions)
    if total == 0:
        return {"available": False, "basis_excluded": basis_excluded}   # unavailable_reason added by callers with a symbol

    from app.services.beat_counts import coverage
    cov = coverage(reactions)            # a beat, miss or meet counts only in a quarter with both an estimate and an actual
    beat, miss, meet = cov["beats"], cov["misses"], cov["meets"]

    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {"min": None, "max": None, "avg": None}
        return {"min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals)}

    vals_1d = [v for r in reactions if (v := _pct(r.pct_change_1d)) is not None]
    vals_3d = [v for r in reactions if (v := _pct(r.pct_change_3d)) is not None]
    vals_5d = [v for r in reactions if (v := _pct(r.pct_change_5d)) is not None]

    s1, s3, s5 = _stats(vals_1d), _stats(vals_3d), _stats(vals_5d)

    latest          = reactions[0]
    latest_date     = str(latest.event_date)
    latest_outcome  = latest.outcome.value
    latest_eps_est  = f"${float(latest.eps_estimate):.2f}" if latest.eps_estimate else "N/A"
    latest_eps_act  = f"${float(latest.eps_actual):.2f}"   if latest.eps_actual   else "N/A"
    latest_1d = _fmt_pct(_pct(latest.pct_change_1d))
    latest_3d = _fmt_pct(_pct(latest.pct_change_3d))
    latest_5d = _fmt_pct(_pct(latest.pct_change_5d))

    beat_sentence = (
        f"Beaten consensus EPS in {beat} of {total} quarters "
        f"({miss} miss, {meet} meet) across the full {total}-quarter history."
        + (f" {excluded_note(basis_excluded)}." if basis_excluded else "")
    )

    return {
        "available":      True,
        "total":          total,
        "quarters_with_data":    cov["with_data"],
        "quarters_without_data": cov["without_data"],
        "beat":           beat,
        "miss":           miss,
        "meet":           meet,
        "basis_excluded": basis_excluded,
        "beat_sentence":  beat_sentence,
        "avg_1d":  _fmt_pct(s1["avg"]),  "max_1d": _fmt_pct(s1["max"]),  "min_1d": _fmt_pct(s1["min"]),
        "avg_3d":  _fmt_pct(s3["avg"]),  "max_3d": _fmt_pct(s3["max"]),  "min_3d": _fmt_pct(s3["min"]),
        "avg_5d":  _fmt_pct(s5["avg"]),  "max_5d": _fmt_pct(s5["max"]),  "min_5d": _fmt_pct(s5["min"]),
        "latest_date":    latest_date,
        "latest_outcome": latest_outcome,
        "latest_eps_est": latest_eps_est,
        "latest_eps_act": latest_eps_act,
        "latest_1d":      latest_1d,
        "latest_3d":      latest_3d,
        "latest_5d":      latest_5d,
    }


# symbol -> why its earnings history is withheld (set by _fetch_context, read by the prompt and stats)
_UNAVAILABLE_REASON: dict[str, str] = {}
# symbol -> the COMPARISON FACTS block (services/note_comparisons), set by _fetch_context, read by both prompts
_COMPARISONS: dict[str, str] = {}
_BUSINESS: dict[str, dict | None] = {}     # the latest 10-K's Item 1 per symbol (note_business), evidence for generation and the check
MODEL_TIMEOUT_SECONDS = 180      # every generation and verification call is bounded


def _stats_block(s: dict) -> str:
    if not s.get("available"):
        reason = s.get("unavailable_reason")
        return f"(No earnings history available: {reason}.)" if reason else "(No earnings history available.)"

    from app.services.licensed_estimates import licensed
    if not licensed():          # LICENSED_ESTIMATES off: the moves only, no beat, miss or estimate
        return f"""\
PRECOMPUTED STATISTICS (authoritative, use these exact figures, do not recount or recalculate):
  1d move avg/max/min : {s['avg_1d']} / {s['max_1d']} / {s['min_1d']}  (n={s['total']})
  3d move avg/max/min : {s['avg_3d']} / {s['max_3d']} / {s['min_3d']}
  5d move avg/max/min : {s['avg_5d']} / {s['max_5d']} / {s['min_5d']}\
"""
    return f"""\
PRECOMPUTED STATISTICS (authoritative, use these exact figures, do not recount or recalculate):
  Beat/miss/meet  : {s['beat_sentence']}
  1d move avg/max/min : {s['avg_1d']} / {s['max_1d']} / {s['min_1d']}  (n={s['total']})
  3d move avg/max/min : {s['avg_3d']} / {s['max_3d']} / {s['min_3d']}
  5d move avg/max/min : {s['avg_5d']} / {s['max_5d']} / {s['min_5d']}
  Most recent quarter ({s['latest_date']}, {(s.get('latest_outcome') or 'unknown').upper()}):
    EPS estimate {s['latest_eps_est']} → actual {s['latest_eps_act']}
    1d {s['latest_1d']}  |  3d {s['latest_3d']}  |  5d {s['latest_5d']}\
"""


# ── Prompt builders ───────────────────────────────────────────────────────────

def _format_market_cap(mc: int | None) -> str:
    if mc is None:
        return "N/A"
    if mc >= 1_000_000_000_000:
        return f"${mc / 1_000_000_000_000:.2f}T"
    if mc >= 1_000_000_000:
        return f"${mc / 1_000_000_000:.2f}B"
    if mc >= 1_000_000:
        return f"${mc / 1_000_000:.0f}M"
    return f"${mc:,}"


# ── Stats object (Python-attached, exact values) ─────────────────────────────

def _build_stats_object(
    ticker: Ticker,
    reactions: list[HistoricalReaction],
) -> dict:
    """Build the stats sub-object with exact DB values. Never fabricate."""
    stats: dict = {
        "market_cap": ticker.market_cap,
        "eps_estimate": None,
        "eps_actual": None,
        "eps_beat_pct": None,
        "revenue_estimate": None,
        "revenue_actual": None,
        "revenue_beat_pct": None,
        "beat_count": None,
        "total_quarters": None,
        "basis_excluded": 0,
        "latest_move_1d": None,
        "latest_outcome": None,
        "latest_quarter_date": None,
    }
    if not reactions:
        stats["unavailable_reason"] = _UNAVAILABLE_REASON.get(ticker.symbol)
        return stats

    precomputed = _precompute_stats(reactions)
    stats["beat_count"] = precomputed.get("beat")
    stats["total_quarters"] = precomputed.get("total")
    stats["quarters_with_data"] = precomputed.get("quarters_with_data")
    stats["quarters_without_data"] = precomputed.get("quarters_without_data")
    stats["basis_excluded"] = precomputed.get("basis_excluded", 0)

    latest = reactions[0]
    stats["latest_quarter_date"] = str(latest.event_date)
    stats["latest_outcome"] = latest.outcome.value
    stats["latest_move_1d"] = _fmt_pct(_pct(latest.pct_change_1d))

    if latest.eps_estimate is not None:
        stats["eps_estimate"] = round(float(latest.eps_estimate), 4)
    if latest.eps_actual is not None:
        stats["eps_actual"] = round(float(latest.eps_actual), 4)
    if latest.eps_estimate and latest.eps_actual and float(latest.eps_estimate) != 0:
        stats["eps_beat_pct"] = round(
            (float(latest.eps_actual) - float(latest.eps_estimate))
            / abs(float(latest.eps_estimate))
            * 100,
            2,
        )

    if latest.revenue_estimate is not None:
        stats["revenue_estimate"] = latest.revenue_estimate
    if latest.revenue_actual is not None:
        stats["revenue_actual"] = latest.revenue_actual
    if latest.revenue_estimate and latest.revenue_actual and latest.revenue_estimate != 0:
        stats["revenue_beat_pct"] = round(
            (latest.revenue_actual - latest.revenue_estimate)
            / abs(latest.revenue_estimate)
            * 100,
            2,
        )

    from app.services.licensed_estimates import licensed, strip_fields
    return stats if licensed() else strip_fields(stats)          # LICENSED_ESTIMATES off: no estimate-based stat is stored


async def _fetch_financials(symbol: str) -> dict | None:
    """Fetch curated financial metrics from Finnhub (best-effort, cached 60 min)."""
    cached = financials_cache.get(symbol)
    if cached is not None:
        return cached

    client = FinnhubClient()
    try:
        raw = await client.get_basic_financials(symbol)
    except Exception as exc:
        print(f"Finnhub financials fetch failed for {symbol}: {redact(exc)}", flush=True)
        return None
    finally:
        await client.close()

    m = raw.get("metric", {})
    if not m:
        return None

    extracted = {
        "forward_pe":           m.get("forwardPE"),
        "pe_ttm":               m.get("peTTM"),
        "ps_ttm":               m.get("psTTM"),
        "peg_ttm":              m.get("pegTTM"),
        "forward_peg":          m.get("forwardPEG"),
        "gross_margin_ttm":     m.get("grossMarginTTM"),
        "gross_margin_5y":      m.get("grossMargin5Y"),
        "operating_margin_ttm": m.get("operatingMarginTTM"),
        "operating_margin_5y":  m.get("operatingMargin5Y"),
        "net_margin_ttm":       m.get("netProfitMarginTTM"),
        "net_margin_5y":        m.get("netProfitMargin5Y"),
        "revenue_growth_ttm":   m.get("revenueGrowthTTMYoy"),
        "eps_growth_ttm":       m.get("epsGrowthTTMYoy"),
        "roe_ttm":              m.get("roeTTM"),
    }

    financials_cache.set(symbol, extracted)
    return extracted


async def merger_context(db: AsyncSession, symbol: str) -> str | None:
    """The merger into this company on file (its exit record), for the note to describe the combined company: VMRK's 10-Q predates
    its merger with AvalonBay, and a note written from it alone described Equity Residential (2026-10-15)."""
    from sqlalchemy import text as _text
    from app.services.ticker_exits import MERGED, REASON_PREFIXES
    row = (await db.execute(_text("""SELECT o.name, a.renamed_on, o.inactive_reason FROM ticker_aliases a JOIN tickers o ON o.symbol = a.old_symbol
        WHERE a.symbol = :s AND o.inactive_reason LIKE :m ORDER BY a.renamed_on DESC LIMIT 1"""), {"s": symbol, "m": REASON_PREFIXES[MERGED] + "%"})).first()
    if row is None:
        return None
    return (f"CORPORATE EVENT: {row.name} merged into {symbol} on {row.renamed_on.isoformat()} ({row.inactive_reason}). Describe the combined "
            "company as it is now. A filing dated before that day describes the company before the merger: say so wherever you use it, "
            "and never present its pre-merger figures (property counts, share counts, revenue) as the combined company's.\n")


def _build_generation_prompt(
    ticker: Ticker,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
    corporate_events: str | None = None,
) -> str:
    name       = ticker.name or ticker.symbol
    sector     = ticker.sector or "N/A"
    industry   = ticker.industry or "N/A"
    market_cap = _format_market_cap(ticker.market_cap)

    if filing and sections:
        mda   = (sections.get("mda") or "").strip()
        risks = (sections.get("risk_factors") or "").strip()
        filing_block = (
            f"RECENT FILING: {filing['form_type']} filed {filing['filing_date']}\n"
            f"--- MD&A EXCERPT ---\n{mda or '(not extracted)'}\n"
            f"--- RISK FACTORS EXCERPT ---\n{risks or '(not extracted)'}\n"
            f"--- END FILING ---"
        )
    else:
        filing_block = "(No SEC filing available. Use general knowledge for this company.)"

    comparisons = _COMPARISONS.get(ticker.symbol) or "COMPARISON FACTS: (none on file)"
    from app.services.note_rules import MAX_POINTS
    business = _business_block(ticker.symbol)

    return f"""\
You are a financial research analyst producing a STRUCTURED research note for {ticker.symbol}.

COMPANY: {ticker.symbol}, {name}
SECTOR: {sector} | INDUSTRY: {industry}
MARKET CAP: {market_cap}
{corporate_events or ""}
{filing_block}

{business}

{comparisons}

OUTPUT FORMAT: Return ONLY a valid JSON object with exactly these keys (no markdown fences, no preamble, no text outside the JSON):

{{
  "bottom_line": "Two to four sentences summarizing what to watch next and why it matters. Neutral: no view on the stock.",
  "what_they_do": "2-4 sentences on core business and revenue model.",
  "highlights": [{{"lead": "short label (2-5 words)", "detail": "1-3 sentences"}}],
  "watch": [{{"lead": "short label", "detail": "1-3 sentences"}}],
  "risks": [{{"lead": "short label", "detail": "1-3 sentences"}}]
}}

RULES:
- At most {MAX_POINTS} points in each of highlights, watch and risks. Fewer is fine, and a section may be empty. Write only the
  points that matter most.
- Every point that states a figure sets it against something: the company's own history (for example a margin against its
  five-year average), the same quarter a year earlier, or sector peers. Take those comparisons from COMPARISON FACTS or the filing.
  Never a bare number. A point with no comparison available states no figure.
- Do not repeat what the ticker page already shows: no beat rate, no count of beats or misses, no EPS surprise, and nothing about
  how the stock moved after past reports.
- The bottom_line summarizes what to watch and stays neutral. No verdict on the stock, no rating, and none of "compelling",
  "exceptional", "strong buy", "undervalued", "overvalued", "bullish", "bearish", "attractive valuation" or anything similar.
- No em dashes or en dashes anywhere. Use commas or separate sentences.
- Use "an" before a number spoken with a vowel sound ("an 18% rise", "an 8-quarter run", "an 11.5% margin") and "a" otherwise.
- Only state facts about the business that appear in the filing excerpt, ITEM 1 (BUSINESS) or COMPARISON FACTS. A second model checks
  every sentence against those sources, and a sentence it cannot confirm there is removed from the note before anyone reads it.
- Do NOT invent revenue figures, margin percentages, ARR, RPO, guidance, or valuation multiples not present in the provided context.
- Do NOT make superlative claims ("strongest", "best ever", "largest") unless the provided context unambiguously supports them.
- Return ONLY valid JSON. No markdown fences. No preamble. No explanation outside the JSON object.\
"""


def _strip_json_fences(text: str) -> str:
    """Strip ```json ... ``` fences if the model wraps its JSON response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _parse_generation_response(raw_text: str) -> dict:
    """Parse and validate the model's structured JSON response.

    Raises ValueError with a clear message on parse failure.
    """
    cleaned = _strip_json_fences(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned invalid JSON: {redact(exc)}") from exc

    # Validate required keys
    required = {"bottom_line", "what_they_do", "highlights", "watch", "risks"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Model response missing required keys: {missing}")

    for section in ("highlights", "watch", "risks"):
        if not isinstance(data[section], list):
            raise ValueError(f"Section '{section}' must be an array")            # empty is allowed: no minimum
        for item in data[section]:
            if not isinstance(item, dict) or "lead" not in item or "detail" not in item:
                raise ValueError(f"Each item in '{section}' must have 'lead' and 'detail'")

    return data


def _serialize_structured_note(structured: dict, ticker: Ticker) -> str:
    """Render the structured note as readable text for the content column + verification."""
    name = ticker.name or ticker.symbol
    lines = [
        f"# {ticker.symbol} ({name})",
        *([f"**Rating: {structured['rating'].title()}**"] if structured.get("rating") else []),
        "",
        structured["bottom_line"],
        "",
        "---",
        "",
        "## What They Do",
        structured["what_they_do"],
        "",
        "---",
        "",
        "## Recent Quarter Highlights",
    ]
    for item in structured["highlights"]:
        lines.append(f"- **{item['lead']}:** {item['detail']}")
    lines += ["", "---", "", "## What to Watch"]
    for item in structured["watch"]:
        lines.append(f"- **{item['lead']}:** {item['detail']}")
    lines += ["", "---", "", "## Key Risks"]
    for item in structured["risks"]:
        lines.append(f"- **{item['lead']}:** {item['detail']}")

    stats = structured.get("stats") or {}
    if stats.get("latest_quarter_date"):
        # LICENSED_ESTIMATES off withholds the outcome (licensed_estimates.strip_fields keeps the key as None): the date alone (BNY,
        # 2026-10-27: "'NoneType' object has no attribute 'upper'" failed every note with an earnings history)
        outcome = stats.get("latest_outcome")
        lines += ["", "---", f"*Most recent quarter: {stats['latest_quarter_date']}" + (f" ({outcome.upper()})" if outcome else "") + "*"]

    return "\n".join(lines)


def _business_block(symbol: str) -> str:
    b = _BUSINESS.get(symbol)
    if not b:
        return "ITEM 1 (BUSINESS): (not available)"
    return f"ITEM 1 (BUSINESS), from the {b['form']} filed {b['filed']}:\n{b['text']}\n--- END ITEM 1 ---"


META_LINE = "*Most recent quarter:"


def _checked_text(content_text: str) -> str:
    """The note as the verifier reads it: without the serialized date line, which is the stats strip's, not a sentence of the note
    (the verifier marked "Most recent quarter: 2026-07-21" unsupported on 25 notes)."""
    return "\n".join(line for line in content_text.split("\n") if not line.startswith(META_LINE)).rstrip()


def _build_verification_prompt(
    note_content: str,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
    ticker: "Ticker",
) -> str:
    if filing and sections:
        mda   = (sections.get("mda") or "").strip()
        risks = (sections.get("risk_factors") or "").strip()
        filing_block = (
            f"FILING: {filing['form_type']} filed {filing['filing_date']}\n"
            f"--- MD&A ---\n{mda or '(not extracted)'}\n"
            f"--- RISK FACTORS ---\n{risks or '(not extracted)'}\n"
            f"--- END ---"
        )
    else:
        filing_block = "(No SEC filing available.)"

    stats = _precompute_stats(reactions)
    stats_block = _stats_block(stats)

    # Mirror the ticker metadata block the generation prompt injects so the
    # verifier can mark those claims supported rather than unsupported.
    ticker_block = (
        f"SYMBOL: {ticker.symbol}\n"
        f"NAME: {ticker.name or ticker.symbol}\n"
        f"SECTOR: {ticker.sector or 'N/A'}\n"
        f"INDUSTRY: {ticker.industry or 'N/A'}\n"
        f"MARKET CAP: {_format_market_cap(ticker.market_cap)}"
    )

    comparisons = _COMPARISONS.get(ticker.symbol) or "COMPARISON FACTS: (none on file)"

    return f"""\
You are a rigorous fact-checker for financial research notes. Verify every factual claim in the note below against the provided evidence sources ONLY.

EVIDENCE SOURCE 1 (SEC FILING TEXT):
{filing_block}

EVIDENCE SOURCE 2 (PRECOMPUTED STATISTICS, ground truth for all numerical earnings claims):
{stats_block}

EVIDENCE SOURCE 3 (TICKER METADATA, live data from the application database injected at generation time):
{ticker_block}

EVIDENCE SOURCE 4 (COMPARISONS computed by the system from stored SEC filings and financial data, ground truth for every
year-earlier, five-year-average and sector-peer comparison):
{comparisons}

EVIDENCE SOURCE 5 (the company's own description of its business, Item 1 of its latest 10-K):
{_business_block(ticker.symbol)}

NOTE TO VERIFY:
{note_content}

CLASSIFICATION RULES:
- "supported": The claim is directly and specifically confirmed by the filing text, precomputed stats, ticker metadata, the comparisons or Item 1. Quote the specific supporting text in "reason".
- "unsupported": The claim is plausible but cannot be confirmed from the provided sources (e.g. drawn from general knowledge, an estimate, or an inference not in the sources). Say why in "reason".
- "contradicted": The claim directly conflicts with the filing text, precomputed stats, ticker metadata, the comparisons or Item 1. Quote the contradiction in "reason".

STRICT RULES:
- Bias toward "unsupported" when in doubt. Do NOT use outside knowledge to mark something "supported".
- The precomputed stats are the sole ground truth for beat/miss/meet counts, averages, and all move percentages.
- Ticker metadata (symbol, name, sector, industry, market cap) is ground truth for those fields.
- Check every specific number, statistic, date, product name, and factual assertion.
- Skip purely subjective or stylistic phrases that contain no verifiable facts.
- Decide each verdict before you write it. "reason" is ONE sentence stating the basis of the settled verdict: never your
  deliberation, never a change of mind ("re-evaluating", "actually"), never a second verdict. A claim whose reason reads as
  deliberation is sent back once and otherwise counted as unsupported.

- "sentence" is the whole sentence of the note the claim comes from, copied exactly, character for character (for a point, the
  sentence of its text; for a point's short label, the label). A sentence that is not confirmed is removed from the note shown.

Output ONLY valid JSON, no preamble, no markdown fences, no explanation outside the JSON:
{{"claims": [{{"claim": "...", "sentence": "...", "verdict": "supported|unsupported|contradicted", "reason": "one sentence"}}]}}\
"""


# ── Context fetcher (shared by generate + re-verify) ─────────────────────────

async def _fetch_context(
    db: AsyncSession, ticker: Ticker
) -> tuple[dict | None, dict | None, list[HistoricalReaction]]:
    """Return (filing, sections, reactions) for a ticker."""
    filing: dict | None = None
    sections: dict | None = None
    edgar = EdgarClient()
    try:
        result = await edgar.get_filing_text_for_ticker(ticker.symbol)
        if result:
            filing, sections = result
    except Exception as exc:
        print(f"EDGAR fetch failed for {ticker.symbol}: {redact(exc)}", flush=True)
    try:
        from app.services.note_business import business_section
        _BUSINESS[ticker.symbol] = await business_section(edgar, ticker.symbol)
    finally:
        await edgar.close()

    rows = await db.execute(
        select(HistoricalReaction)
        .where(
            HistoricalReaction.ticker_id == ticker.id,
            HistoricalReaction.event_type == EventType.EARNINGS,
        )
        .order_by(HistoricalReaction.event_date.desc())
        .limit(20)
    )
    reactions = list(rows.scalars().all())
    if await is_excluded(db, ticker.symbol):
        reactions = []      # rows stay stored; the note says why there is no earnings history
        _UNAVAILABLE_REASON[ticker.symbol] = EXCLUSION_REASON
    try:
        from app.services.note_comparisons import comparison_block
        _COMPARISONS[ticker.symbol] = await comparison_block(db, ticker.symbol, ticker.sector, await _fetch_financials(ticker.symbol))
    except Exception as exc:
        print(f"Comparison facts failed for {ticker.symbol}: {redact(exc)}", flush=True)
        _COMPARISONS[ticker.symbol] = "COMPARISON FACTS: (none on file)"
    basis_unclear = await basis_mismatch_dates(db, ticker.id)
    for r in reactions:
        r.basis_mismatch = r.event_date in basis_unclear   # transient marker read by _precompute_stats
    return filing, sections, reactions


# ── Verification core ─────────────────────────────────────────────────────────

async def _run_verification(
    note_content: str,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
    ticker: "Ticker",
) -> tuple[dict, str, int, int]:
    """Call Opus to verify the note. Returns (verification_dict, model_used, input_tokens, output_tokens)."""
    prompt = _build_verification_prompt(_checked_text(note_content), filing, sections, reactions, ticker)
    client = AnthropicClient(timeout=MODEL_TIMEOUT_SECONDS, max_retries=2)
    raw = await client.verify_research_note(prompt)

    model_used    = raw["model_used"]
    from app.services.verification_verdicts import UNSETTLED_REASON, parse_claims, self_corrected, summary_of
    claims = parse_claims(raw["content"])          # tolerant of the note's own quotation marks unescaped (AVY, CARR 2026-10-28)
    in_tokens, out_tokens = raw["input_tokens"], raw["output_tokens"]
    # a claim whose reason reads as deliberation is verified once more on its own; a second such answer counts as unsupported
    for i, c in enumerate(claims):
        if not self_corrected(c["reason"], c["verdict"]):
            continue
        again = await _reverify_claim(client, c["claim"], filing, sections, reactions, ticker)
        in_tokens += again["input_tokens"]
        out_tokens += again["output_tokens"]
        if again["claim"] is not None and not self_corrected(again["claim"]["reason"], again["claim"]["verdict"]):
            claims[i] = {**c, "verdict": again["claim"]["verdict"], "reason": again["claim"]["reason"]}
        else:
            claims[i] = {**c, "verdict": "unsupported", "reason": UNSETTLED_REASON}
    from app.services.note_claims import NOTE_CHECK_VERSION
    verification = {"claims": claims, "summary": summary_of(claims),      # the summary is counted from the verdicts, never the model's
                    "version": NOTE_CHECK_VERSION}

    print(
        f"Verification complete: "
        f"{verification['summary']['supported']} supported, "
        f"{verification['summary']['unsupported']} unsupported, "
        f"{verification['summary']['contradicted']} contradicted "
        f"| {in_tokens} in / {out_tokens} out tokens",
        flush=True,
    )

    contradicted = [c for c in verification["claims"] if c["verdict"] == "contradicted"]
    if contradicted:
        print(f"  ⚠ CONTRADICTED CLAIMS ({len(contradicted)}):", flush=True)
        for c in contradicted:
            print(f"    • {c['claim'][:120]}", flush=True)
            print(f"      Reason: {c['reason'][:160]}", flush=True)

    return verification, model_used, in_tokens, out_tokens


async def _reverify_claim(client, claim: str, filing, sections, reactions, ticker) -> dict:
    """One claim verified on its own against the same sources (the "note" is the claim). Returns {claim: {claim, verdict, reason} | None,
    input_tokens, output_tokens}."""
    from app.services.verification_verdicts import parse_claims
    raw = await client.verify_research_note(_build_verification_prompt(claim, filing, sections, reactions, ticker))
    try:
        rows = parse_claims(raw["content"])
    except ValueError:
        rows = []
    return {"claim": rows[0] if rows else None, "input_tokens": raw["input_tokens"], "output_tokens": raw["output_tokens"]}


async def _add_to_daily_spend(db: AsyncSession, cost: float | None, now: datetime) -> None:
    """Accumulate today's estimated spend under one dated key, so /health reads a stored number."""
    from app.services.system_metadata_service import get_value, set_value
    if cost is None:
        key = f"research_gen:unpriced:{now.strftime('%Y-%m-%d')}"
        raw = await get_value(db, key)
        await set_value(db, key, str((int(raw) if raw else 0) + 1))
        from app.services import ai_spend
        await ai_spend.add(db, None, now, commit=False)
        return
    key = f"research_gen:spend:{now.strftime('%Y-%m-%d')}"
    raw = await get_value(db, key)
    await set_value(db, key, f"{(float(raw) if raw else 0.0) + cost:.4f}")
    from app.services import ai_spend
    await ai_spend.add(db, cost, now, commit=False)          # the site-wide cap counts every feature's spend


# ── Generate (two-phase: immediate upsert + background work) ─────────────────

async def start_research_note_generation(
    db: AsyncSession,
    ticker_id: uuid.UUID | None,
    symbol: str | None,
) -> ResearchNote:
    """Upsert a placeholder row with status='generating' and return immediately."""
    ticker = await _resolve_ticker(db, ticker_id, symbol)

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(ResearchNote)
        .values(
            ticker_id          = ticker.id,
            generated_at       = now,
            source_filings     = [],
            content            = "",
            model_used         = "",
            input_tokens       = 0,
            output_tokens      = 0,
            verification       = None,
            verified_at        = None,
            verification_model = None,
            structured_content = None,
            status             = "generating",
            error              = None,
        )
        .on_conflict_do_update(
            constraint="uq_research_notes_ticker",
            set_=dict(
                generated_at       = now,
                source_filings     = [],
                content            = "",
                model_used         = "",
                input_tokens       = 0,
                output_tokens      = 0,
                verification       = None,
                verified_at        = None,
                verification_model = None,
                structured_content = None,
                status             = "generating",
                error              = None,
                updated_at         = now,
            ),
        )
        .returning(ResearchNote)
    )
    note = (await db.execute(stmt)).scalar_one()
    await db.commit()
    await db.refresh(note)
    return note


async def _generate_structured(prompt: str, symbol: str) -> tuple[dict, dict]:
    """Generate, check the draft against services/note_rules, retry once with the broken rules named, then enforce them in
    code. Returns (structured note, {model_used, input_tokens, output_tokens} over both calls)."""
    from app.services.note_rules import enforce, note_problems
    client = AnthropicClient(timeout=MODEL_TIMEOUT_SECONDS, max_retries=2)
    gen = await client.generate_research_note(prompt)
    structured = _parse_generation_response(gen["content"])
    used = {"model_used": gen["model_used"], "input_tokens": gen["input_tokens"], "output_tokens": gen["output_tokens"], "attempts": 1}
    problems = note_problems(structured)
    if problems:
        retry = prompt + "\n\nYOUR PREVIOUS DRAFT BROKE THESE RULES; write the note again without them:\n" + "\n".join(f"- {p}" for p in problems)
        again = await client.generate_research_note(retry)
        used["input_tokens"] += again["input_tokens"]
        used["output_tokens"] += again["output_tokens"]
        used["attempts"] = 2
        try:
            structured = _parse_generation_response(again["content"])
        except ValueError:
            pass                                            # the first draft, enforced below
    used["problems_first_draft"] = problems
    print(f"Research note generated for {symbol}: {used['input_tokens']} in / {used['output_tokens']} out tokens, "
          f"{used['attempts']} attempt(s), {len(problems)} rule(s) broken in the first draft", flush=True)
    return enforce(structured), used


async def run_research_note_background(
    ticker_id: uuid.UUID,
    symbol: str,
    charge: dict | None = None,
    regenerated: bool = False,
) -> None:
    """Background task: fetch context, generate with Sonnet, verify with Opus.

    Opens its own DB session — the request session is already closed.
    ``charge`` is the rate-limit use recorded for the caller ({"ip", "at"}); a
    failure at either phase refunds it, so a visitor never pays for no note.
    A note that would lose more than note_claims.MAX_LOST sentences to its check (or hold an unconfirmed claim no sentence of it
    holds) is written again once (``regenerated``); if the second note would too, it is held and the digest names it.
    """
    from app.services.draft_limiter import RESEARCH_GENERATION_POLICY, refund_use
    from app.services.research_cost import estimate_cost_usd

    async def _refund(db: AsyncSession) -> None:
        if charge:
            await refund_use(db, RESEARCH_GENERATION_POLICY, charge["ip"], charge.get("at"))

    async with AsyncSessionLocal() as db:
        try:
            ticker = await _resolve_ticker(db, ticker_id, symbol)
            filing, sections, reactions = await _fetch_context(db, ticker)

            # ── Phase 1: Sonnet generation (structured JSON) ─────────────
            prompt = _build_generation_prompt(ticker, filing, sections, reactions, await merger_context(db, ticker.symbol))
            structured, gen = await _generate_structured(prompt, ticker.symbol)

            # Attach Python-computed stats (exact DB values, never model-generated)
            stats_obj = _build_stats_object(ticker, reactions)
            structured["stats"] = stats_obj

            # Attach Finnhub financial metrics (best-effort, never model-generated)
            financials_obj = await _fetch_financials(symbol)
            structured["financials"] = financials_obj

            # Serialize to readable text for content column + verifier
            content_text = _serialize_structured_note(structured, ticker)

            source_filings: list[dict] = []
            if filing:
                source_filings.append({
                    "form_type":        filing["form_type"],
                    "accession_number": filing["accession_number"],
                    "filing_date":      filing["filing_date"],
                    "url":              filing.get("url", ""),
                })

            now = datetime.now(timezone.utc)
            gen_cost = estimate_cost_usd(gen["model_used"], gen["input_tokens"], gen["output_tokens"])
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker.id)
                .values(
                    content            = content_text,
                    structured_content = structured,
                    model_used         = gen["model_used"],
                    input_tokens       = gen["input_tokens"],
                    output_tokens      = gen["output_tokens"],
                    estimated_cost_usd = gen_cost,
                    source_filings     = source_filings,
                    status             = "verifying",
                    data_version       = 3,
                    updated_at         = now,
                )
            )
            await _add_to_daily_spend(db, gen_cost, now)   # spent whether or not verification passes
            await db.commit()

        except Exception as exc:
            print(f"Research note generation failed for {symbol}: {exc!r}", flush=True)
            from app.services import user_errors
            await user_errors.record("research_note", exc, symbol)          # the digest gets the real error; the note says PLAIN
            now = datetime.now(timezone.utc)
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker_id)
                .values(status="failed", error=redact(exc), updated_at=now)
            )
            await db.commit()
            await _refund(db)
            return

        # ── Phase 2: Opus verification (best-effort) ─────────────────
        try:
            verification, verification_model, ver_in, ver_out = await _run_verification(
                content_text, filing, sections, reactions, ticker
            )
            now = datetime.now(timezone.utc)
            ver_cost = estimate_cost_usd(verification_model, ver_in, ver_out)
            total_cost = None if gen_cost is None and ver_cost is None else (gen_cost or 0.0) + (ver_cost or 0.0)
            verdict = check_outcome(structured, verification)
            status = "complete" if verdict is None else ("verifying" if not regenerated else STATUS_HELD)
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker.id)
                .values(
                    verification       = verification,
                    verified_at        = now,
                    verification_model = verification_model,
                    verification_input_tokens  = ver_in,
                    verification_output_tokens = ver_out,
                    estimated_cost_usd = total_cost,
                    status             = status,
                    error              = None if verdict is None else f"held: {verdict}",
                    updated_at         = now,
                )
            )
            await _add_to_daily_spend(db, ver_cost, now)
            await db.commit()
            if verdict is not None:
                print(f"Research note for {symbol}: {verdict}" + (", held" if regenerated else ", writing it again"), flush=True)
                if regenerated:
                    from app.services import user_errors
                    await user_errors.record("research_note_held", f"held after a second writing: {verdict}", symbol)
                    await _refund(db)
                else:
                    await run_research_note_background(ticker_id, symbol, charge, regenerated=True)
        except Exception as exc:
            print(f"Verification failed for {symbol}: {exc!r} — note withheld from visitors", flush=True)
            from app.services import user_errors
            await user_errors.record("research_verify", exc, symbol)
            now = datetime.now(timezone.utc)
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker.id)
                .values(status=STATUS_VERIFICATION_FAILED, error=f"verification failed: {redact(exc)}", updated_at=now)
            )
            await db.commit()
            await _refund(db)   # the visitor gets no note, so the use is not theirs to pay


STATUS_VERIFICATION_FAILED = "verification_failed"
STATUS_HELD = "held"           # the check could not confirm too much of the note, twice: never served, named in the digest


def check_outcome(structured: dict | None, verification: dict | None) -> str | None:
    """Pure: why a checked note may not be served as it stands, or None: it would lose more than MAX_LOST sentences, or an
    unconfirmed claim sits in no sentence of it (so it cannot be removed)."""
    from app.services.note_claims import MAX_LOST, review
    r = review(structured, verification)
    if len(r["lost"]) > MAX_LOST:
        return f"the check could not confirm {len(r['lost'])} sentences (more than {MAX_LOST})"
    if r["unlocated"]:
        return f"{len(r['unlocated'])} unconfirmed claim(s) found in no sentence of the note"
    return None


# ── Who may read a note ───────────────────────────────────────────────────────

def is_verified(note: ResearchNote) -> bool:
    """True only when the second-model check actually ran and its result is stored."""
    return note.status == "complete" and note.verification is not None


def verification_failed(note: ResearchNote) -> bool:
    """The check errored, or the note was marked complete without one (older rows)."""
    return note.status == STATUS_VERIFICATION_FAILED or (note.status == "complete" and note.verification is None)


def withheld(note: ResearchNote) -> bool:
    """A visitor never sees this note: its check errored (verification_failed), it was held (STATUS_HELD), or an unconfirmed claim
    sits in no sentence of it, so the served note could not leave it out (note_claims; a note checked before 2026-10-28 until the
    nightly checks it again)."""
    if verification_failed(note) or note.status == STATUS_HELD:
        return True
    if is_verified(note):
        from app.services.note_claims import review
        return bool(review(note.structured_content, note.verification)["unlocated"])
    return False


# ── Re-verify existing note ───────────────────────────────────────────────────

async def verify_existing_note(
    db: AsyncSession,
    ticker_id: uuid.UUID | None,
    symbol: str | None,
) -> ResearchNote:
    ticker = await _resolve_ticker(db, ticker_id, symbol)

    note_row = await db.execute(
        select(ResearchNote).where(ResearchNote.ticker_id == ticker.id)
    )
    note = note_row.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="No research note found. Generate one first.")

    filing, sections, reactions = await _fetch_context(db, ticker)
    try:
        verification, verification_model, ver_in, ver_out = await _run_verification(
            note.content, filing, sections, reactions, ticker
        )
    except Exception as exc:
        from app.services import user_errors
        await user_errors.record("research_verify", exc, ticker.symbol)
        raise HTTPException(status_code=502, detail=user_errors.plain("research_verify"))

    now = datetime.now(timezone.utc)
    note.verification       = verification
    note.verified_at        = now
    note.verification_model = verification_model
    note.verification_input_tokens = ver_in
    note.verification_output_tokens = ver_out
    note.status             = "complete"   # a successful re-check releases a note whose first check failed
    note.error              = None
    note.updated_at         = now
    await db.commit()
    await db.refresh(note)
    return note


async def recheck_note(symbol: str) -> str:
    """The nightly's check of a note checked before the current check (note_claims.NOTE_CHECK_VERSION): verified again with Item 1 of
    the 10-K as evidence. A note the check now passes (check_outcome) keeps its text with the new verification; one that would lose
    more than MAX_LOST sentences, or hold an unconfirmed claim it cannot place, is written again once and held if the second note fails
    too. Returns "rechecked", "rewritten" or "failed: ..."; a failed check leaves the note as it was."""
    from app.services.research_cost import estimate_cost_usd
    async with AsyncSessionLocal() as db:
        ticker = await _resolve_ticker(db, None, symbol)
        note = (await db.execute(select(ResearchNote).where(ResearchNote.ticker_id == ticker.id))).scalar_one_or_none()
        if note is None or not is_verified(note):
            return "failed: no checked note"
        filing, sections, reactions = await _fetch_context(db, ticker)
        try:
            verification, model, ver_in, ver_out = await _run_verification(note.content, filing, sections, reactions, ticker)
        except Exception as exc:
            from app.services import user_errors
            await user_errors.record("research_verify", exc, symbol)
            return f"failed: {redact(exc)[:120]}"
        now = datetime.now(timezone.utc)
        await _add_to_daily_spend(db, estimate_cost_usd(model, ver_in, ver_out), now)
        if check_outcome(note.structured_content, verification) is not None:
            await db.commit()
            ticker_id = ticker.id
        else:
            note.verification, note.verified_at, note.verification_model = verification, now, model
            note.verification_input_tokens, note.verification_output_tokens, note.updated_at = ver_in, ver_out, now
            await db.commit()
            return "rechecked"
    await run_research_note_background(ticker_id=ticker_id, symbol=symbol, regenerated=True)
    return "rewritten"


# ── Fetch ─────────────────────────────────────────────────────────────────────

STUCK_TIMEOUT_SECONDS = 180  # 3 minutes


async def get_research_note(
    db: AsyncSession,
    ticker_id: uuid.UUID | None,
    symbol: str | None,
) -> ResearchNote | None:
    ticker = await _resolve_ticker(db, ticker_id, symbol)
    row = await db.execute(
        select(ResearchNote).where(ResearchNote.ticker_id == ticker.id)
    )
    note = row.scalar_one_or_none()
    if note is None:
        return None

    # Stuck-job guard: if generating/verifying for > 3 minutes, mark failed
    if note.status in ("generating", "verifying"):
        age = (datetime.now(timezone.utc) - note.updated_at).total_seconds()
        if age > STUCK_TIMEOUT_SECONDS:
            note.status = "failed"
            note.error = "Generation timed out"
            note.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(note)

    return note


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_ticker(
    db: AsyncSession,
    ticker_id: uuid.UUID | None,
    symbol: str | None,
) -> Ticker:
    if ticker_id:
        t = await db.get(Ticker, ticker_id)
    else:
        result = await db.execute(
            select(Ticker).where(Ticker.symbol == symbol.upper())  # type: ignore[union-attr]
        )
        t = result.scalar_one_or_none()

    if t is None:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return t
