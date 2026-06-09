"""Service layer for generating and verifying AI research notes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
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
        "latest_move_1d": None,
        "latest_outcome": None,
        "latest_quarter_date": None,
    }
    if not reactions:
        return stats

    precomputed = _precompute_stats(reactions)
    stats["beat_count"] = precomputed.get("beat")
    stats["total_quarters"] = precomputed.get("total")

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

    return stats


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
You are a financial research analyst producing a STRUCTURED research note for {ticker.symbol}.

COMPANY: {ticker.symbol} — {name}
SECTOR: {sector} | INDUSTRY: {industry}
MARKET CAP: {market_cap}

{filing_block}

{stats_block}

EARNINGS TABLE (for qualitative context — do NOT count rows, recompute averages, or derive any statistics; use the precomputed values above for all numerical claims):
{table_block}

OUTPUT FORMAT: Return ONLY a valid JSON object with exactly these keys (no markdown fences, no preamble, no text outside the JSON):

{{
  "rating": "bullish" | "neutral" | "bearish",
  "bottom_line": "One paragraph (3-5 sentences) synthesizing the investment picture — what matters most right now.",
  "what_they_do": "2-4 sentences on core business and revenue model.",
  "highlights": [
    {{"lead": "short bold label (2-5 words)", "detail": "1-3 sentence analysis"}},
    ...
  ],
  "watch": [
    {{"lead": "short label", "detail": "1-3 sentence analysis"}},
    ...
  ],
  "risks": [
    {{"lead": "short label", "detail": "1-3 sentence analysis"}},
    ...
  ]
}}

RULES:
- "rating" MUST be exactly one of: "bullish", "neutral", "bearish". Base it on the overall picture from filings + earnings data.
- 3-6 items in each of highlights, watch, and risks.
- The precomputed statistics above are authoritative. Use those exact figures for any numerical claim about earnings history.
- Do NOT count, rank, or compute any statistics yourself from the table.
- Do NOT make superlative claims ("strongest", "best ever", "largest") unless the precomputed stats unambiguously support them.
- Only state facts about the business that appear in the filing excerpt or are well-established public knowledge.
- Do NOT invent revenue figures, margin percentages, ARR, RPO, guidance, or valuation multiples not present in the provided context.
- Do NOT include a "stats" key — numerical stats are attached separately by the system.
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
        raise ValueError(f"Model returned invalid JSON: {exc}") from exc

    # Validate required keys
    required = {"rating", "bottom_line", "what_they_do", "highlights", "watch", "risks"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Model response missing required keys: {missing}")

    if data["rating"] not in ("bullish", "neutral", "bearish"):
        raise ValueError(f"Invalid rating: {data['rating']!r}")

    for section in ("highlights", "watch", "risks"):
        if not isinstance(data[section], list) or len(data[section]) == 0:
            raise ValueError(f"Section '{section}' must be a non-empty array")
        for item in data[section]:
            if not isinstance(item, dict) or "lead" not in item or "detail" not in item:
                raise ValueError(f"Each item in '{section}' must have 'lead' and 'detail'")

    return data


def _serialize_structured_note(structured: dict, ticker: Ticker) -> str:
    """Render the structured note as readable text for the content column + verification."""
    name = ticker.name or ticker.symbol
    lines = [
        f"# {ticker.symbol} — {name}",
        f"**Rating: {structured['rating'].title()}**",
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

    stats = structured.get("stats", {})
    if stats.get("latest_quarter_date"):
        lines += [
            "",
            "---",
            f"*Most recent quarter: {stats['latest_quarter_date']}"
            f" ({stats.get('latest_outcome', 'N/A').upper()})*",
        ]

    return "\n".join(lines)


def _build_verification_prompt(
    note_content: str,
    filing: dict | None,
    sections: dict | None,
    reactions: list[HistoricalReaction],
    ticker: "Ticker",
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

    # Mirror the ticker metadata block the generation prompt injects so the
    # verifier can mark those claims supported rather than unsupported.
    ticker_block = (
        f"SYMBOL: {ticker.symbol}\n"
        f"NAME: {ticker.name or ticker.symbol}\n"
        f"SECTOR: {ticker.sector or 'N/A'}\n"
        f"INDUSTRY: {ticker.industry or 'N/A'}\n"
        f"MARKET CAP: {_format_market_cap(ticker.market_cap)}"
    )

    return f"""\
You are a rigorous fact-checker for financial research notes. Verify every factual claim in the note below against the provided evidence sources ONLY.

EVIDENCE SOURCE 1 — SEC FILING TEXT:
{filing_block}

EVIDENCE SOURCE 2 — PRECOMPUTED STATISTICS (these are ground truth for all numerical earnings claims):
{stats_block}

EVIDENCE SOURCE 3 — TICKER METADATA (live data from the application database injected at generation time):
{ticker_block}

NOTE TO VERIFY:
{note_content}

CLASSIFICATION RULES:
- "supported": The claim is directly and specifically confirmed by the filing text, precomputed stats, or ticker metadata. Quote the specific supporting text in "evidence".
- "unsupported": The claim is plausible but cannot be confirmed from the provided sources (e.g. drawn from general knowledge, an estimate, or an inference not in the sources). Explain why in "evidence".
- "contradicted": The claim directly conflicts with the filing text, precomputed stats, or ticker metadata. Quote the contradiction in "evidence".

STRICT RULES:
- Bias toward "unsupported" when in doubt — do NOT use outside knowledge to mark something "supported".
- The precomputed stats are the sole ground truth for beat/miss/meet counts, averages, and all move percentages.
- Ticker metadata (symbol, name, sector, industry, market cap) is ground truth for those fields.
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
    ticker: "Ticker",
) -> tuple[dict, str]:
    """Call Opus to verify the note. Returns (verification_dict, model_used)."""
    prompt = _build_verification_prompt(note_content, filing, sections, reactions, ticker)
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


async def run_research_note_background(
    ticker_id: uuid.UUID,
    symbol: str,
) -> None:
    """Background task: fetch context, generate with Sonnet, verify with Opus.

    Opens its own DB session — the request session is already closed.
    """
    async with AsyncSessionLocal() as db:
        try:
            ticker = await _resolve_ticker(db, ticker_id, symbol)
            filing, sections, reactions = await _fetch_context(db, ticker)

            # ── Phase 1: Sonnet generation (structured JSON) ─────────────
            prompt = _build_generation_prompt(ticker, filing, sections, reactions)
            client = AnthropicClient()
            gen = await client.generate_research_note(prompt)

            print(
                f"Research note generated for {ticker.symbol}: "
                f"{gen['input_tokens']} in / {gen['output_tokens']} out tokens",
                flush=True,
            )

            # Parse structured JSON from model response
            structured = _parse_generation_response(gen["content"])

            # Attach Python-computed stats (exact DB values, never model-generated)
            stats_obj = _build_stats_object(ticker, reactions)
            structured["stats"] = stats_obj

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
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker.id)
                .values(
                    content            = content_text,
                    structured_content = structured,
                    model_used         = gen["model_used"],
                    input_tokens       = gen["input_tokens"],
                    output_tokens      = gen["output_tokens"],
                    source_filings     = source_filings,
                    status             = "verifying",
                    updated_at         = now,
                )
            )
            await db.commit()

        except Exception as exc:
            print(f"Research note generation failed for {symbol}: {exc!r}", flush=True)
            now = datetime.now(timezone.utc)
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker_id)
                .values(status="failed", error=str(exc), updated_at=now)
            )
            await db.commit()
            return

        # ── Phase 2: Opus verification (best-effort) ─────────────────
        try:
            verification, verification_model = await _run_verification(
                content_text, filing, sections, reactions, ticker
            )
            now = datetime.now(timezone.utc)
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker.id)
                .values(
                    verification       = verification,
                    verified_at        = now,
                    verification_model = verification_model,
                    status             = "complete",
                    updated_at         = now,
                )
            )
            await db.commit()
        except Exception as exc:
            print(
                f"Verification failed for {symbol}: {exc!r} — marking complete without verification",
                flush=True,
            )
            now = datetime.now(timezone.utc)
            await db.execute(
                update(ResearchNote)
                .where(ResearchNote.ticker_id == ticker.id)
                .values(status="complete", updated_at=now)
            )
            await db.commit()


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
            note.content, filing, sections, reactions, ticker
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
