"""The second reader of an earnings release: the model (Sonnet) returns the quarter's GAAP diluted EPS, its quarter-end date and
the exact sentence or table row it read it from. Code verifies the quote appears verbatim in the exhibit, contains the number and
carries none of the disqualifying words; a figure is stored only when this reading and the pattern parser's agree to the cent. Any
disagreement is recorded as unread with both readings, and the morning digest lists it.
"""
from __future__ import annotations

import json
import re
from datetime import date

from app.services.research_cost import estimate_cost_usd

MODEL = "claude-sonnet-4-6"
MAX_CHARS = 120_000                 # an exhibit beyond this is cut (the figure sits in the first pages); the cut is noted
DISQUALIFIERS = re.compile(r"non-?\s?gaap|adjusted|\bcore\b|operating\s+eps|\bffo\b|funds\s+from\s+operations|normali[sz]ed|comparable"
                           r"|fiscal[- ]year|full[- ]year|year[- ]ended|twelve[- ]months|year[- ]to[- ]date", re.I)
CONTINUING = re.compile(r"continuing\s+operations", re.I)
TOTAL_NEAR_CONTINUING = re.compile(r"per\s+(?:common\s+)?share\s*[—–-]+\s*diluted|diluted\s+(?:net\s+)?(?:earnings|income)\s+per", re.I)

PROMPT = """You are reading the text of an earnings press release filed with the SEC (an 8-K exhibit). Return JSON only, no prose:
{{"eps": <number or null>, "period_end": "<YYYY-MM-DD or null>", "quote": "<the exact sentence or table row, copied verbatim, that states the figure>"}}

The figure wanted is GAAP diluted earnings per share for the most recent quarter the release reports:
- the quarter, never the fiscal year, full year, year to date or twelve months;
- GAAP, never non-GAAP, adjusted, core, operating, normalized or comparable EPS, never FFO;
- the total, never continuing operations alone;
- a loss is negative (a figure written "$(0.35)" is -0.35).
Copy the quote exactly as the text reads it (one sentence, or one table row with its label and numbers); never paraphrase. If the release
states no such figure, return eps null and quote null. The report date is {report_date}.

TEXT:
{text}"""


def build_prompt(text: str, report_date: date | None) -> tuple[str, bool]:
    """Pure: (prompt, cut) with the exhibit flattened and cut at MAX_CHARS."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    cut = len(flat) > MAX_CHARS
    return PROMPT.format(report_date=report_date.isoformat() if report_date else "unknown", text=flat[:MAX_CHARS]), cut


def parse_model_json(content: str) -> dict | None:
    """Pure: the JSON object in the model's reply, or None."""
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    eps = d.get("eps")
    try:
        eps = float(eps) if eps is not None else None
    except (TypeError, ValueError):
        eps = None
    pe = d.get("period_end")
    try:
        pe = date.fromisoformat(str(pe)[:10]) if pe else None
    except ValueError:
        pe = None
    return {"eps": eps, "period_end": pe, "quote": (d.get("quote") or "").strip() or None}


def _number_forms(eps: float) -> list[str]:
    a = abs(eps)
    forms = [f"{a:.2f}", f"{a:,.2f}"]
    if a == int(a):
        forms += [f"{int(a)}"]
    return forms


def verify_quote(exhibit_text: str, quote: str | None, eps: float | None) -> list[str]:
    """Pure: why the model's quote cannot stand, or [] when it appears verbatim in the exhibit, contains the number, and carries no
    disqualifying word (non-GAAP, adjusted, core, operating EPS, FFO, funds from operations, normalized, comparable, fiscal year, full
    year, year ended, twelve months, year to date) and no continuing-operations figure without a total."""
    problems = []
    if not quote:
        return ["no quote"]
    # verbatim in substance: whitespace, dollar signs, thousands commas and case are formatting, not words (a table row the model copies
    # as "$ 1.34 $ 2.68 (50) %" against the exhibit's "$1.34 $2.68 (50)%" is the same row)
    norm = lambda t: re.sub(r"[\s$,]+", "", t or "").lower()
    flat = norm(exhibit_text)
    q = re.sub(r"\s+", " ", quote).strip()
    if norm(q) not in flat:
        problems.append("quote is not verbatim in the exhibit")
    if eps is None:
        problems.append("no figure")
    elif not any(f in q for f in _number_forms(eps)):
        problems.append(f"quote does not contain {eps:+.2f}")
    bad = sorted({m.group(0).lower() for m in DISQUALIFIERS.finditer(q)})
    if bad:
        problems.append("disqualifying word(s): " + ", ".join(bad))
    if CONTINUING.search(q) and not TOTAL_NEAR_CONTINUING.search(q.split("continuing")[0]):
        problems.append("continuing operations without a total")
    return problems


def agree(pattern_eps: float | None, model_eps: float | None) -> bool:
    """Pure: both readers read a figure and agree to the cent."""
    return pattern_eps is not None and model_eps is not None and round(pattern_eps, 2) == round(model_eps, 2)


def decide(pattern: dict | None, model: dict | None, exhibit_text: str) -> tuple[float | None, str]:
    """Pure: (the figure to store, the note). A figure stores only when the pattern parser and the verified model reading agree to the
    cent; otherwise the note carries both readings for the unread record and the digest."""
    p = pattern["eps"] if pattern else None
    p_text_only = f"pattern {p:+.2f} ({pattern['how']})" if pattern else "pattern read nothing"
    if model is None:
        return None, f"{p_text_only}; no model reading"
    m = model.get("eps") if model else None
    problems = verify_quote(exhibit_text, (model or {}).get("quote"), m) if model and model.get("eps") is not None else (["model read nothing"] if model else ["no model reading"])
    p_text = f"pattern {p:+.2f} ({pattern['how']})" if pattern else "pattern read nothing"
    m_text = (f"model {m:+.2f}" if m is not None else "model read nothing") + (f' "{(model or {}).get("quote") or ""}"'[:120] if model and model.get("quote") else "")
    if problems and model and model.get("eps") is not None:
        return None, f"{p_text}; {m_text}; model quote rejected: {'; '.join(problems)}"
    if agree(p, m):
        return p, f"both readers {p:+.2f}"
    return None, f"{p_text}; {m_text}; readers disagree"


async def model_read(client, text: str, report_date: date | None) -> dict:
    """The model's reading of an exhibit: {eps, period_end, quote, model, input_tokens, output_tokens, cost_usd, cut, raw}."""
    prompt, cut = build_prompt(text, report_date)
    out = await client.read_release_eps(prompt)
    parsed = parse_model_json(out["content"]) or {"eps": None, "period_end": None, "quote": None}
    return {**parsed, "model": out["model_used"], "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
            "cost_usd": estimate_cost_usd(out["model_used"], out["input_tokens"], out["output_tokens"]), "cut": cut, "raw": out["content"][:400]}
