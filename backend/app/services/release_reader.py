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
from app.services.valuation import _COMPARISON_CUE, basic_only_label, current_column, header_order, states_diluted_eps

MODEL = "claude-sonnet-4-6"
MAX_CHARS = 120_000                 # an exhibit beyond this is cut (the figure sits in the first pages); the cut is noted
DISQUALIFIERS = re.compile(r"non-?\s?gaap|adjusted|\bcore\b|operating\s+eps|\bffo\b|funds\s+from\s+operations|normali[sz]ed|comparable"
                           r"|fiscal[- ]year|full[- ]year|year[- ]ended|twelve[- ]months|year[- ]to[- ]date", re.I)
CONTINUING = re.compile(r"continuing\s+operations", re.I)
HEADING_NOT_VERBATIM = "the heading is not verbatim in the exhibit"
BASIC_ROW = "a row labelled basic, and the release states diluted EPS"
TOTAL_NEAR_CONTINUING = re.compile(r"per\s+(?:common\s+)?share\s*[—–-]+\s*diluted|diluted\s+(?:net\s+)?(?:earnings|income)\s+per", re.I)

PROMPT = """You are reading the text of an earnings press release filed with the SEC (an 8-K exhibit). Return JSON only, no prose:
{{"eps": <number or null>, "period_end": "<YYYY-MM-DD or null>", "quote": "<the exact sentence or table row, copied verbatim, that states the figure>",
 "columns": "<for a table row: the heading cells that name the periods of its columns, copied verbatim (e.g. 'Three Months Ended June 30, 2026 2025'); else null>",
 "column": <for a table row: the 1-based position, among the per-share numbers in the quote, of the figure returned; else null>}}

The figure wanted is GAAP diluted earnings per share for the most recent quarter the release reports:
- the quarter, never the fiscal year, full year, year to date or twelve months;
- GAAP, never non-GAAP, adjusted, core, operating, normalized or comparable EPS, never FFO;
- the total, never continuing operations alone;
- a loss is negative (a figure written "$(0.35)" is -0.35);
- in a table, the current quarter's column is the one its heading names: some releases list the prior year's column first (a heading
  "2025 2026 Change" puts the current quarter second, "3Q25 2Q26 3Q26" puts it third), so read the heading, never assume the first number;
- a release that reports a month and the quarter (a heading "September Quarter": the month's columns first, then the quarter's) or the
  year to date before the quarter ("Nine Months Ended ... Three Months Ended") states the quarter's figure in the quarter's columns, never
  the month's or the year to date's: in "September Quarter 2026 2025 Change 2026 2025 Change ... $ 1.08 $ 0.52 109 % $ 4.37 $ 4.45" the
  quarter's figure is 4.37, the third number;
- in a block headed "Diluted:" with continuing and discontinued operations lines, the figure is the block's total line (net earnings);
- a per-share figure in a table whose share count is diluted ("Average diluted equivalent common shares") is diluted EPS, even when its
  own row reads "Per share available to common shareholders";
- the quote is one row or one sentence only, never two rows joined.
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
    col = d.get("column")
    try:
        col = int(col) if col is not None else None
    except (TypeError, ValueError):
        col = None
    return {"eps": eps, "period_end": pe, "quote": (d.get("quote") or "").strip() or None,
            "columns": (str(d.get("columns") or "").strip() or None), "column": col}


def _number_forms(eps: float) -> list[str]:
    a = abs(eps)
    forms = [f"{a:.2f}", f"{a:,.2f}"]
    if a == int(a):
        forms += [f"{int(a)}"]
    return forms


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
_DASHES = dict.fromkeys(map(ord, "\u2212\u2013\u2014"), "-")
_PER_SHARE_FIGURE = re.compile(r"\(?-?\d{1,4}(?:,\d{3})*\.\d{2}\)?")      # a per-share amount in a quote: two decimals ("(50) %" and "(3.3 )" are not)


def _norm(t: str | None) -> str:
    """Formatting is not wording: whitespace, dollar signs, thousands commas, zero-width characters and case are dropped, and the
    minus, en and em dashes read as a hyphen."""
    return re.sub(r"[\s$,]+", "", (t or "").translate(_ZERO_WIDTH).translate(_DASHES)).lower()


def _norm_map(t: str) -> tuple[str, list[int]]:
    """Pure: (the normalized text, the original index of each kept character)."""
    kept, idx = [], []
    for i, ch in enumerate((t or "").translate(_ZERO_WIDTH).translate(_DASHES)):
        if ch.isspace() or ch in "$,":
            continue
        kept.append(ch.lower()); idx.append(i)
    return "".join(kept), idx


def _label_and_numbers(q: str) -> tuple[str, str]:
    """Pure: a quoted row split at its first amount: (the label, the run of numbers)."""
    m = re.search(r"[\$(]?\s?-?\d", q)
    return (q, "") if m is None else (q[:m.start()], q[m.start():])


def verify_quote(exhibit_text: str, quote: str | None, eps: float | None, columns: str | None = None, column: int | None = None) -> list[str]:
    """Pure: why the model's quote cannot stand, or [] when it appears verbatim in the exhibit, contains the number, and carries no
    disqualifying word (non-GAAP, adjusted, core, operating EPS, FFO, funds from operations, normalized, comparable, fiscal year, full
    year, year ended, twelve months, year to date) and no continuing-operations figure without a total.

    Verbatim means the whole quote, or the row's label and its run of numbers each verbatim (a model copies a row's numbers from one
    table and its label from the heading above it: CLX's "Diluted net earnings per share $ 1.34 $ 2.68 (50) %" against the exhibit's
    "Diluted earnings per share ... As reported (GAAP) $ 1.34 $ 2.68 (50) %"); then the exhibit's own label on that row of numbers may
    carry no disqualifying word either. A row with two or more per-share numbers needs `column` (the position of the figure), the
    number there must be the figure, and the column must follow the heading's order. The order is taken from the exhibit itself, from
    the heading nearest before the row (valuation.header_order, as the pattern parser reads it), and from the model's `columns` only when
    the exhibit has no such heading; `columns` not verbatim in the exhibit is still a problem (decide() may turn it into a note). A quote
    from a row labelled basic alone is refused when the release states diluted EPS anywhere."""
    problems = []
    if not quote:
        return ["no quote"]
    flat, idx = _norm_map(exhibit_text)
    q = re.sub(r"\s+", " ", quote).strip()
    row_at = None                                         # where the row sits in the exhibit (original index), for the heading above it
    if _norm(q) in flat:
        row_at = idx[flat.find(_norm(q))] if _norm(q) else None
    else:
        label, numbers = _label_and_numbers(q)
        nl, nn = _norm(label), _norm(numbers)
        if nl and nn and nl in flat and nn in flat:
            at = flat.find(nn)
            row_at = idx[at]
            row_label = re.split(r"\d", exhibit_text[max(0, idx[at] - 160):idx[at]])[-1]      # the exhibit's own label after the previous number
            bad = sorted({m.group(0).lower() for m in DISQUALIFIERS.finditer(row_label)})
            if bad:
                problems.append("the exhibit's row is labelled with disqualifying word(s): " + ", ".join(bad))
        else:
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
    if basic_only_label(_label_and_numbers(q)[0]) and states_diluted_eps(exhibit_text):
        problems.append(BASIC_ROW)
    figures = _PER_SHARE_FIGURE.findall(_label_and_numbers(q)[1])
    if eps is not None and len(figures) >= 2 and not compared_sentence(q, eps):
        if column is None:
            problems.append("a row of several figures without the column read")
        elif not 1 <= column <= len(figures) or abs(_amount(figures[column - 1]) - abs(eps)) > 0.005:
            problems.append(f"column {column} does not hold {eps:+.2f}")
        if columns and _norm(columns) not in flat:
            problems.append(HEADING_NOT_VERBATIM)
        cur = current_column(exhibit_text[:row_at], len(figures)) if row_at is not None else None
        order = None if cur is not None else ((header_order(exhibit_text[:row_at]) if row_at is not None else None) or (header_order(columns) if columns else None))
        if cur is not None and column is not None and column != cur + 1:
            problems.append(f"the heading names column {cur + 1} as the quarter's but column {column} was read")
        if order:
            if order == "prior-first" and column == 1:
                problems.append("the heading lists the prior year first but column 1 was read")
            if order == "current-first" and column == 2:
                problems.append("the heading lists the current period first but column 2 was read")
    return problems


_SENTENCE_FIGURE = re.compile(r"\b(?:was|were|of|totaled|reached)\s+\$?\s?\(?-?\d")


def compared_sentence(quote: str, eps: float) -> bool:
    """Pure: the quote is a sentence stating the figure first and a prior period's after a comparison ("Net earnings per diluted share was
    $0.86, compared with $0.82 for the same period in 2025.", PLD 2026-10-15): no column applies, the figure is the first amount."""
    q = re.sub(r"\s+", " ", quote or "")
    m = _SENTENCE_FIGURE.search(q)
    if not m:
        return False
    figs = _PER_SHARE_FIGURE.findall(q[m.start():])
    return bool(figs) and abs(_amount(figs[0]) - abs(eps)) <= 0.005 and bool(_COMPARISON_CUE.search(q[m.end():]))


def _amount(s: str) -> float:
    return abs(float(s.replace(",", "").strip("()-")))


def in_diluted_block(exhibit_text: str, quote: str | None) -> bool:
    """Pure: the quoted row sits under a "Diluted:" heading, after the block's "Basic:" lines (CARR's "Diluted: Continuing operations ...
    Discontinued operations ... Net earnings (loss) $ 0.60 $ 0.68 ...", 2026-07-28): the row is diluted EPS though its own label says so
    only through the heading."""
    flat, idx = _norm_map(exhibit_text or "")
    nq = _norm(quote)
    at = flat.find(nq) if nq else -1
    if at < 0:
        return False
    head = flat[max(0, at - 260):at]
    d = head.rfind("diluted:")
    return d >= 0 and "basic:" not in head[d:]


def in_diluted_share_table(exhibit_text: str, quote: str | None) -> bool:
    """Pure: the quoted per-share row sits in a table whose share count is diluted ("Average diluted equivalent common shares" within
    the next 800 characters, PGR 2026-10-14), so the row is diluted EPS."""
    flat = re.sub(r"\s+", " ", exhibit_text or "")
    q = re.sub(r"\s+", " ", quote or "").strip()
    at = flat.find(q) if q else -1
    return at >= 0 and bool(re.search(r"average\s+diluted\s+(?:equivalent\s+)?common\s+shares", flat[at:at + len(q) + 800], re.I))


def diluted_row(quote: str | None) -> bool:
    """Pure: the quoted row or sentence names diluted EPS in its own label ("Diluted earnings per common share", "per diluted share")."""
    q = re.sub(r"\s+", " ", quote or "")
    return bool(re.search(r"\bdiluted\b|assuming\s+dilution", _label_and_numbers(q)[0], re.I)) or bool(re.search(r"per\s+diluted\s+share", q, re.I))


def basic_row(quote: str | None) -> bool:
    """Pure: the quoted row's own label names basic EPS and not diluted ("Reported earnings per share (basic)")."""
    return basic_only_label(_label_and_numbers(re.sub(r"\s+", " ", quote or ""))[0])


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
    problems = verify_quote(exhibit_text, (model or {}).get("quote"), m, (model or {}).get("columns"), (model or {}).get("column")) if model and model.get("eps") is not None else (["model read nothing"] if model else ["no model reading"])
    p_text = f"pattern {p:+.2f} ({pattern['how']})" if pattern else "pattern read nothing"
    m_text = (f"model {m:+.2f}" if m is not None else "model read nothing") + (f' "{(model or {}).get("quote") or ""}"'[:120] if model and model.get("quote") else "")
    heading_note = ""
    eps_row = (diluted_row(model.get("quote")) or in_diluted_block(exhibit_text, model.get("quote")) or in_diluted_share_table(exhibit_text, model.get("quote"))
               or (basic_row(model.get("quote")) and not states_diluted_eps(exhibit_text)))
    if problems == [HEADING_NOT_VERBATIM] and p is not None and m is not None and p == m and eps_row:
        # the column order came from the exhibit's own heading, both readers read the same figure exactly, and the row is diluted EPS,
        # or basic EPS in a release that states no diluted EPS anywhere: the model's paraphrased heading alone is a note, not a
        # rejection (EIX 2026-07-30 diluted, ED 2026-08-06 basic)
        problems, heading_note = [], "; note: the model's heading is not verbatim in the exhibit (column order read from the exhibit)"
    if problems and model and model.get("eps") is not None:
        return None, f"{p_text}; {m_text}; model quote rejected: {'; '.join(problems)}"
    if agree(p, m):
        return p, f"both readers {p:+.2f}{heading_note}"
    return None, f"{p_text}; {m_text}; readers disagree"


async def model_read(client, text: str, report_date: date | None) -> dict:
    """The model's reading of an exhibit: {eps, period_end, quote, model, input_tokens, output_tokens, cost_usd, cut, raw}."""
    prompt, cut = build_prompt(text, report_date)
    out = await client.read_release_eps(prompt)
    parsed = parse_model_json(out["content"]) or {"eps": None, "period_end": None, "quote": None}
    return {**parsed, "model": out["model_used"], "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
            "cost_usd": estimate_cost_usd(out["model_used"], out["input_tokens"], out["output_tokens"]), "cut": cut, "raw": out["content"][:400]}
