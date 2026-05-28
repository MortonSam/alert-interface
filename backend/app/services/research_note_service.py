"""Service layer for generating and verifying AI research notes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.research_note import ResearchNote
from app.models.ticker import Ticker
from app.services.anthropic_client import AnthropicClient
from app.services.edgar_client import EdgarClient


# ── Precomputed stats ─────────────────────────────────────────────────────────

def _pct(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _fmt_pct(v: float | None) -> str:
    return f"{v:+.2f}%" if v is not None else "N/A"


def _precompute_stats(reactions: list[HistoricalReaction]) -> dict:
    """Return a dict of authoritative, Python-computed statistics."""
    total = len(reactions)
    if total == 0:
        return {"available": False}

    beat  = sum(1 for r in reactions if r.outcome.value == "beat")
    miss  = sum(1 for r in reactions if r.outcome.value == "miss")
    meet  = sum(1 for r in reactions if r.outcome.value == "meet")

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
    )

    return {
        "available":      True,
        "total":          total,
        "beat":           beat,
        "miss":           miss,
        "meet":           meet,
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


def _stats_block(s: dict) -> str:
    if not s.get("available"):
        return "(No earnings history available.)"

    return f"""\
PRECOMPUTED STATISTICS (authoritative — use these exact figures, do not recount or recalculate):
  Beat/miss/meet  : {s['beat_sentence']}
  1d move avg/max/min : {s['avg_1d']} / {s['max_1d']} / {s['min_1d']}  (n={s['total']})
  3d move avg/max/min : {s['avg_3d']} / {s['max_3d']} / {s['min_3d']}
  5d move avg/max/min : {s['avg_5d']} / {s['max_5d']} / {s['min_5d']}
  Most recent quarter ({s['latest_date']}, {s['latest_outcome'].upper()}):
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


def _build_generation_prompt(
    ticker: Ticker,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
) -> str:
    name       = ticker.name or ticker.symbol
    sector     = ticker.sector or "N/A"
    industry   = ticker.industry or "N/A"
    market_cap = _format_market_cap(ticker.market_cap)

    if filing and sections:
        mda   = sections.get("mda", "").strip()
        risks = sections.get("risk_factors", "").strip()
        filing_block = (
            f"RECENT FILING: {filing['form_type']} filed {filing['filing_date']}\n"
            f"--- MD&A EXCERPT ---\n{mda or '(not extracted)'}\n"
            f"--- RISK FACTORS EXCERPT ---\n{risks or '(not extracted)'}\n"
            f"--- END FILING ---"
        )
    else:
        filing_block = "(No SEC filing available — use general knowledge for this company.)"

    stats = _precompute_stats(reactions)
    stats_block = _stats_block(stats)

    if reactions:
        rows = []
        for r in reactions:
            eps_est = f"${float(r.eps_estimate):.2f}" if r.eps_estimate else "—"
            eps_act = f"${float(r.eps_actual):.2f}"   if r.eps_actual   else "—"
            pct_1d  = f"{float(r.pct_change_1d):+.1f}%" if r.pct_change_1d else "—"
            pct_3d  = f"{float(r.pct_change_3d):+.1f}%" if r.pct_change_3d else "—"
            pct_5d  = f"{float(r.pct_change_5d):+.1f}%" if r.pct_change_5d else "—"
            rows.append(
                f"| {r.event_date} | {r.outcome.value:7} | {eps_est:8} | {eps_act:8} "
                f"| {pct_1d:7} | {pct_3d:7} | {pct_5d:7} |"
            )
        header = "| Date       | Outcome | EPS Est  | EPS Act  |  1d%    |  3d%    |  5d%    |"
        sep    = "|------------|---------|----------|----------|---------|---------|---------|"
        table_block = "\n".join([header, sep] + rows)
    else:
        table_block = "(No earnings data.)"

    return f"""\
You are a financial research analyst. Write a concise research note for {ticker.symbol}.

COMPANY: {ticker.symbol} — {name}
SECTOR: {sector} | INDUSTRY: {industry}
MARKET CAP: {market_cap}

{filing_block}

{stats_block}

EARNINGS TABLE (for qualitative context — do NOT count rows, recompute averages, or derive any statistics; use the precomputed values above for all numerical claims):
{table_block}

RULES:
- The precomputed statistics above are authoritative. Use those exact figures for any numerical claim about earnings history.
- Do NOT count, rank, or compute any statistics yourself from the table.
- Do NOT make superlative claims ("strongest", "best ever", "largest") unless the precomputed stats unambiguously support them.
- Only state facts about the business that appear in the filing excerpt or are well-established public knowledge.
- Do not invent revenue figures, margin percentages, or guidance numbers not in the filing.

Write a research one-pager in markdown with EXACTLY these four sections:

## What They Do
[2-3 sentences on core business and revenue model]

## Recent Quarter Highlights
[4-6 bullet points — draw from the filing excerpt and the precomputed most-recent-quarter stats above]

## What to Watch
[3-4 forward-looking items from the filing]

## Key Risks
[3 bullet points from the filing's risk factors]

Target 400-600 words. Be specific; cite numbers from the filing or the precomputed stats.\
"""


def _build_verification_prompt(
    note_content: str,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
) -> str:
    if filing and sections:
        mda   = sections.get("mda", "").strip()
        risks = sections.get("risk_factors", "").strip()
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

    return f"""\
You are a rigorous fact-checker for financial research notes. Verify every factual claim in the note below against the provided evidence sources ONLY.

EVIDENCE SOURCE 1 — SEC FILING TEXT:
{filing_block}

EVIDENCE SOURCE 2 — PRECOMPUTED STATISTICS (these are ground truth for all numerical earnings claims):
{stats_block}

NOTE TO VERIFY:
{note_content}

CLASSIFICATION RULES:
- "supported": The claim is directly and specifically confirmed by the filing text or precomputed stats. Quote the specific supporting text in "evidence".
- "unsupported": The claim is plausible but cannot be confirmed from the provided sources (e.g. drawn from general knowledge, an estimate, or an inference not in the sources). Explain why in "evidence".
- "contradicted": The claim directly conflicts with the filing text or precomputed stats. Quote the contradiction in "evidence".

STRICT RULES:
- Bias toward "unsupported" when in doubt — do NOT use outside knowledge to mark something "supported".
- The precomputed stats are the sole ground truth for beat/miss/meet counts, averages, and all move percentages.
- Check every specific number, statistic, date, product name, and factual assertion.
- Skip purely subjective or stylistic phrases that contain no verifiable facts.
- The summary counts must exactly equal the number of claims in the claims array.

Output ONLY valid JSON — no preamble, no markdown fences, no explanation outside the JSON:
{{"claims": [{{"claim": "...", "status": "supported|unsupported|contradicted", "evidence": "..."}}], "summary": {{"supported": N, "unsupported": N, "contradicted": N}}}}\
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
        print(f"EDGAR fetch failed for {ticker.symbol}: {exc}", flush=True)
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
    return filing, sections, reactions


# ── Verification core ─────────────────────────────────────────────────────────

async def _run_verification(
    note_content: str,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
) -> tuple[dict, str]:
    """Call Opus to verify the note. Returns (verification_dict, model_used)."""
    prompt = _build_verification_prompt(note_content, filing, sections, reactions)
    client = AnthropicClient()
    raw = await client.verify_research_note(prompt)

    model_used    = raw["model_used"]
    response_text = raw["content"].strip()

    # Strip accidental markdown fences if present
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    verification = json.loads(response_text)

    print(
        f"Verification complete: "
        f"{verification['summary']['supported']} supported, "
        f"{verification['summary']['unsupported']} unsupported, "
        f"{verification['summary']['contradicted']} contradicted "
        f"| {raw['input_tokens']} in / {raw['output_tokens']} out tokens",
        flush=True,
    )

    contradicted = [c for c in verification["claims"] if c["status"] == "contradicted"]
    if contradicted:
        print(f"  ⚠ CONTRADICTED CLAIMS ({len(contradicted)}):", flush=True)
        for c in contradicted:
            print(f"    • {c['claim'][:120]}", flush=True)
            print(f"      Evidence: {c['evidence'][:160]}", flush=True)

    return verification, model_used


# ── Generate ──────────────────────────────────────────────────────────────────

async def generate_research_note(
    db: AsyncSession,
    ticker_id: uuid.UUID | None,
    symbol: str | None,
) -> ResearchNote:
    ticker = await _resolve_ticker(db, ticker_id, symbol)
    filing, sections, reactions = await _fetch_context(db, ticker)

    # Generate — upstream failure → 502 with a clear message
    prompt = _build_generation_prompt(ticker, filing, sections, reactions)
    client = AnthropicClient()
    try:
        gen = await client.generate_research_note(prompt)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Research note generation failed: {exc}. Please try again.",
        )

    print(
        f"Research note generated for {ticker.symbol}: "
        f"{gen['input_tokens']} in / {gen['output_tokens']} out tokens",
        flush=True,
    )

    # Verify — best-effort: never discard the note if verification fails for any reason
    verification: dict | None = None
    verification_model: str | None = None
    verified_at_dt: datetime | None = None
    try:
        verification, verification_model = await _run_verification(
            gen["content"], filing, sections, reactions
        )
        verified_at_dt = datetime.now(timezone.utc)
    except Exception as exc:
        print(
            f"Verification failed for {ticker.symbol}: {exc!r} "
            f"— saving note without verification",
            flush=True,
        )

    source_filings: list[dict] = []
    if filing:
        source_filings.append({
            "form_type":        filing["form_type"],
            "accession_number": filing["accession_number"],
            "filing_date":      filing["filing_date"],
            "url":              filing.get("url", ""),
        })

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(ResearchNote)
        .values(
            ticker_id          = ticker.id,
            generated_at       = now,
            source_filings     = source_filings,
            content            = gen["content"],
            model_used         = gen["model_used"],
            input_tokens       = gen["input_tokens"],
            output_tokens      = gen["output_tokens"],
            verification       = verification,
            verified_at        = verified_at_dt,
            verification_model = verification_model,
        )
        .on_conflict_do_update(
            constraint="uq_research_notes_ticker",
            set_=dict(
                generated_at       = now,
                source_filings     = source_filings,
                content            = gen["content"],
                model_used         = gen["model_used"],
                input_tokens       = gen["input_tokens"],
                output_tokens      = gen["output_tokens"],
                verification       = verification,
                verified_at        = verified_at_dt,
                verification_model = verification_model,
                updated_at         = now,
            ),
        )
        .returning(ResearchNote)
    )
    note = (await db.execute(stmt)).scalar_one()
    await db.commit()
    await db.refresh(note)
    return note


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
        raise HTTPException(status_code=404, detail="No research note found — generate one first")

    filing, sections, reactions = await _fetch_context(db, ticker)
    try:
        verification, verification_model = await _run_verification(
            note.content, filing, sections, reactions
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Verification failed: {exc}. Please try again.",
        )

    now = datetime.now(timezone.utc)
    note.verification       = verification
    note.verified_at        = now
    note.verification_model = verification_model
    note.updated_at         = now
    await db.commit()
    await db.refresh(note)
    return note


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def get_research_note(
    db: AsyncSession,
    ticker_id: uuid.UUID | None,
    symbol: str | None,
) -> ResearchNote | None:
    ticker = await _resolve_ticker(db, ticker_id, symbol)
    row = await db.execute(
        select(ResearchNote).where(ResearchNote.ticker_id == ticker.id)
    )
    return row.scalar_one_or_none()


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
