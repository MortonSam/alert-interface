"""Ivy's stock walkthrough: seven steps that teach a newcomer to read one stock, rebuilt nightly (scripts/build_walkthroughs).

Every sentence here that states a number is built by rule from stored, dated data (services/walkthrough_data gathers it); the
model only adds at most one story sentence per step, and step 7's risk sentences, through services/walkthrough_story, which
verifies each. Quick checks come from services/walkthrough_checks. A step without trustworthy data says so in one line and the
summary marks it. Wording lives in this module's constants and the step builders, and every visible string is listed in
backend/ops/reports/wording_ivy_walkthrough_2026-10-19.md for approval.

Payload of a step: {n, key, question, status ("ok" | "partial" | "absent"), absent (the one honest line, or None), numbers
[{label, value, as_of}], sentences [rule-built], story (filled by the story step), idea {concept, title, text}, chart, check,
deeper [{label, value, as_of}], source {label, url}, summary (one line for the summary screen), uncertain (or None)}.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from app.services.briefing import description_text, fmt_date, short_name
from app.services.move_comparison import compare_moves
from app.services import walkthrough_checks as C

WALKTHROUGH_VERSION = 1
MINUTES = 3                                       # "about 3 minutes", stated on the entry
FAST_GROWTH_PCT = 50.0                            # sales growth this fast is listed among what's still uncertain
CHART_EVERY = 5                                   # chart points: every fifth session, plus the last
PE_MEDIAN_AGREEMENT = 0.15                        # the series' median must match the stored five-year median within this (one decimal rounding)
CLOSING_LINE = "Ivy doesn't make buy or sell calls."

QUESTIONS = {
    1: "What does it do, and how does it make money?",
    2: "Is the business getting bigger?",
    3: "How much of each sale does it keep?",
    4: "What has the stock done, and was it the company or the market?",
    5: "Is it expensive?",
    6: "What's coming up?",
    7: "What could go wrong?",
}
KEYS = {1: "business", 2: "growth", 3: "margins", 4: "stock", 5: "valuation", 6: "upcoming", 7: "risks"}

# "The idea": the concept behind each step, true of any stock. No figure here may be about one company.
IDEAS = {
    "segments": ("Segments", "A company's annual report, the 10-K, splits its sales into segments. The segment that brings in most of the money is what really drives the business, whatever the company is best known for."),
    "growth": ("Growth", "Growth compares a quarter with the same quarter a year earlier, so seasonal swings cancel out. Sales growth shows demand. Earnings growth shows whether that demand turns into profit."),
    "margins": ("Margins", "A margin is the slice of each sales dollar a company keeps. A rising margin usually means pricing power or lower costs, a falling one competition or rising costs. Compare margins within an industry, since a grocer and a software maker run on very different slices."),
    "cyclical": ("Cyclical businesses", "Some businesses swing between feast and famine. When the price of what they sell rises and falls with supply and demand, as with memory chips, oil or steel, the slice they keep can change sharply within a few years, so one good year says little about the next."),
    "market_vs_company": ("Market or company", "Every stock moves partly with the whole market and partly on its own news. Comparing it with the S&P 500 and with similar companies separates the two. If they all rose together, it was the market. If it rose alone, it was the company."),
    "pe": ("P/E", "P/E is the share price divided by the company's earnings per share over the last year, so it is what investors pay for each dollar of profit. A high P/E means they expect profits to grow, a low one that they doubt it. It says most next to the same company's past and similar companies."),
    "report_move": ("The report move", "Around an earnings report a stock can jump or drop in a single day. Options prices show how big a move traders expect. Comparing that with the stock's typical move after past reports tells you whether this one is priced as unusually big."),
    "risk_factors": ("Risk factors", "Every annual report has a section called Item 1A, Risk Factors, where the company must list what could hurt it. A listed risk is a disclosure, not a prediction, and reading the list tells you what could change the story."),
}
KNOWN_CONCEPT_LINE = "You know {title} from {learned_from}. Here's how {name} compares."
REIT_NOTE = ("Real estate trusts are usually judged by funds from operations rather than earnings, because depreciation makes their "
             "earnings look small, so a trust's P/E says less than other companies'.")
REIT_GROWTH_NOTE = "Real estate trusts are usually judged by funds from operations per share rather than earnings per share, and Ivy doesn't show that figure yet."
GROWTH_IN_REVIEW = "Growth figures are still being checked and are not shown on this site until they pass."
PE_IN_REVIEW = "P/E figures are still being checked and are not shown on this site until they pass."
SEGMENT_REASONS = {
    "no 10-K": "There is no annual report (10-K) on file at the SEC.",
    "no full fiscal year": "Its annual report's data has no full fiscal year.",
    "do not add up": "The segment figures in its annual report do not add up to its total sales, so Ivy doesn't show them.",
    "no revenue split": "Its annual report does not split its sales by segment or product.",
    "no XBRL instance": "Its annual report has no machine-readable figures.",
}
RISK_REASONS = {
    "no 10-K": "There is no annual report (10-K) on file at the SEC.",
    "could not be found": "Ivy couldn't find the risk factors section in its annual report.",
    "could not be read": "Ivy couldn't read the risk factors in its annual report.",
}
CONFIRMATION_WORDS = {"confirmed": "Confirmed by the company", "estimated": "Estimated, not confirmed", "expected_unconfirmed": "Expected, not confirmed",
                      "expected_window": "Expected window from past reports"}
TIMING_WORDS = {"bmo": "before the market opens", "amc": "after the market closes"}


# ── formatting ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def money_words(x: float) -> str:
    """"$133.2 billion", "$1.4 trillion", "$850.0 million": one decimal, the unit in words."""
    for unit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(x) >= unit:
            return f"${x / unit:,.1f} {word}"
    return f"${x:,.0f}"


def cents(x: float) -> str:
    """In a sentence: "81¢", "a loss of 9¢"."""
    return f"{round(x)}¢" if round(x) >= 0 else f"a loss of {abs(round(x))}¢"


def cents_value(x: float) -> str:
    """As a displayed figure: "81¢", "−9¢"."""
    return f"{round(x)}¢" if round(x) >= 0 else f"−{abs(round(x))}¢"


def signed(x: float) -> str:
    return f"{x:+.1f}%"


def moved(x: float) -> str:
    return f"rose {abs(x):.1f}%" if x > 0 else f"fell {abs(x):.1f}%" if x < 0 else "was unchanged"


def day_words(d: date) -> str:
    return d.strftime("%a, ") + fmt_date(d)


def iso_dates(text: str) -> str:
    """Pure: "2026-06-29" written "Jun 29, 2026" (a stored reason carries ISO dates; the site never shows them)."""
    import re
    return re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: fmt_date(date(int(m[1]), int(m[2]), int(m[3]))), text)


def _num(label: str, value: str, as_of: str) -> dict:
    return {"label": label, "value": value, "as_of": as_of}


def _step(n: int, *, status: str, numbers=None, sentences=None, idea: str | None = None, absent: str | None = None, chart=None, check=None,
          deeper=None, source=None, summary: str | None = None, uncertain: str | None = None) -> dict:
    title, text = IDEAS[idea] if idea else (None, None)
    return {"n": n, "key": KEYS[n], "question": QUESTIONS[n], "status": status, "absent": absent, "numbers": numbers or [], "sentences": sentences or [],
            "story": None, "idea": {"concept": idea, "title": title, "text": text} if idea else None, "chart": chart, "check": check,
            "deeper": deeper or [], "source": source, "summary": summary, "uncertain": uncertain}


def cant(name: str, why: str) -> str:
    return f"Ivy can't show this for {name} yet. {why}"


def _reason(raw: str | None, table: dict[str, str], fallback: str) -> str:
    for key, words in table.items():
        if raw and key in raw:
            return words
    return fallback


def predates(merger: dict | None, filed: date | None) -> bool:
    """Pure: a merger into this company completed after a filing (or profile) dated `filed` (the VMRK rule)."""
    return bool(merger and merger.get("date") and (filed is None or merger["date"] > filed))


def merger_line(merger: dict, what: str) -> str:
    return f"It merged with {short_name(merger['name'])} on {fmt_date(merger['date'])}, and {what} predates the merger."


# ── step 1: what it does ────────────────────────────────────────────────────────────────────────────────────────────────────

def step_business(name: str, profile: dict | None, segments: dict | None, merger: dict | None) -> dict:
    desc = description_text((profile or {}).get("short_description"))
    profile_ok = bool(desc) and not predates(merger, (profile or {}).get("latest_filing_date"))
    seg_ok = bool(segments and segments.get("ok")) and not predates(merger, segments.get("filed"))
    if not profile_ok and not seg_ok:
        if merger and (desc or (segments and segments.get("ok"))):
            why = f"It merged with {short_name(merger['name'])} on {fmt_date(merger['date'])}, and its last annual report and company description both describe the business before the merger."
        else:
            why = _reason((segments or {}).get("reason"), SEGMENT_REASONS, "Its company description and sales split are not on file.")
        return _step(1, status="absent", absent=cant(name, why), idea="segments", summary=None)
    sentences, numbers, deeper = [], [], []
    as_of_profile = (profile or {}).get("fetched_at")
    if profile_ok:
        sentences.append(desc)
    check = source = None
    summary = None
    if seg_ok:
        segs, total = segments["segments"], segments["total"]
        top = segs[0]
        period = f"fiscal year to {fmt_date(segments['end'])}"
        as_of = f"Fiscal year to {fmt_date(segments['end'])}, 10-K filed {fmt_date(segments['filed'])}"
        numbers = [_num("Sales in its last fiscal year", money_words(total), as_of), _num(f"From {top['label']}", f"{top['share']:.1f}%", as_of)]
        if top["share"] >= 50:
            sentences.append(f"Most of its sales come from {top['label']}, {top['share']:.1f}% of {money_words(total)} in the {period}.")
        else:
            sentences.append(f"Its biggest line is {top['label']}, at {top['share']:.1f}% of {money_words(total)} in the {period}.")
        if len(segs) > 1:
            sentences.append(f"Next comes {segs[1]['label']} at {segs[1]['share']:.1f}%.")
        deeper = [_num(g["label"], f"{g['share']:.1f}% ({money_words(g['value'])})", as_of) for g in segs]
        check = C.segments_check(name, segs, period)
        source = {"label": f"10-K filed {fmt_date(segments['filed'])}", "url": segments.get("url")}
        summary = f"{name} makes {'most' if top['share'] >= 50 else 'the biggest share'} of its money from {top['label']} ({top['share']:.1f}% of sales)."
    else:
        why = (merger_line(merger, "its last annual report") if merger and segments and segments.get("ok")
               else _reason((segments or {}).get("reason"), SEGMENT_REASONS, "Its sales split is not on file."))
        sentences.append(f"Ivy can't split {name}'s sales yet. {why}")
        summary = f"What {name} does, from its company description." if profile_ok else None
    if profile_ok and as_of_profile:
        deeper.append(_num("Company description", "Intrinio company profile", f"Fetched {fmt_date(as_of_profile.date() if hasattr(as_of_profile, 'date') else as_of_profile)}"))
    return _step(1, status="ok" if (profile_ok and seg_ok) else "partial", numbers=numbers, sentences=sentences, idea="segments", check=check,
                 deeper=deeper, source=source, summary=summary)


# ── step 2: growth ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def ttm_growth(rows: list[dict]) -> tuple[float, float, float, date] | None:
    """Pure: (sum of the last four quarters, sum of the same quarters a year earlier, percent change, last quarter end) when the
    four latest stored quarters are consecutive and each has both figures and no hold."""
    four = sorted(rows, key=lambda r: r["period_end"])[-4:]
    if len(four) < 4 or any(r.get("held_reason") or r.get("value") is None or r.get("year_ago_value") is None for r in four):
        return None
    if any(not 80 <= (b["period_end"] - a["period_end"]).days <= 100 for a, b in zip(four, four[1:])):
        return None
    now, before = sum(float(r["value"]) for r in four), sum(float(r["year_ago_value"]) for r in four)
    if before <= 0:
        return None
    return now, before, round((now / before - 1) * 100, 1), four[-1]["period_end"]


def step_growth(name: str, rows: list[dict] | None, sector: str | None, enabled: bool) -> dict:
    if not enabled:
        return _step(2, status="absent", absent=cant(name, GROWTH_IN_REVIEW), idea="growth")
    rev = [r for r in rows or [] if r["metric"] == "revenue"]
    eps = {r["period_end"]: r for r in rows or [] if r["metric"] == "eps"}
    newest = max(rev, key=lambda r: r["period_end"], default=None)
    agreed = [r for r in rev if not r.get("held_reason") and r.get("value") is not None and (r.get("growth_pct") is not None or r.get("phrase"))]
    latest = max(agreed, key=lambda r: r["period_end"], default=None)     # the newest quarter both readers agree on (it carries its own date)
    if newest and newest.get("held_reason") or not latest:
        why = (f"{iso_dates(newest['held_reason'])}." if newest and newest.get("held_reason")
               else "Its filings and its earnings releases do not yet agree on these figures.")
        return _step(2, status="absent", absent=cant(name, why), idea="growth")
    end = latest["period_end"]
    q_as_of = f"Quarter to {fmt_date(end)}"
    numbers = [_num("Sales, latest quarter against a year earlier", signed(float(latest["growth_pct"])) if latest["growth_pct"] is not None else latest["phrase"], q_as_of)]
    sentences = [f"In the quarter to {fmt_date(end)}, {name}'s sales were {money_words(float(latest['value']))}, {latest['phrase']}."]
    t = ttm_growth(rev)
    check = summary = uncertain = None
    if t:
        now, before, pct, t_end = t
        numbers.append(_num("Sales, last four quarters against the four before", signed(pct), f"Four quarters to {fmt_date(t_end)}"))
        sentences.append(f"Over the last four quarters, sales came to {money_words(now)}, {'up' if pct >= 0 else 'down'} {abs(pct):.1f}% on the four quarters before.")
        check = C.growth_check(name, pct, f"four quarters to {fmt_date(t_end)}")
        summary = f"Its sales {'grew' if pct >= C.GROWTH_FLAT_PCT else 'shrank' if pct <= -C.GROWTH_FLAT_PCT else 'held about flat'} over the last four quarters ({signed(pct)})."
        uncertain = "Whether growth this fast lasts." if pct >= FAST_GROWTH_PCT else None
    else:
        summary = f"Its sales in the latest quarter were {latest['phrase']}."
    if sector == "Real Estate":
        sentences.append(REIT_GROWTH_NOTE)
    elif end in eps and eps[end].get("value") is not None and not eps[end].get("held_reason"):
        e = eps[end]
        sentences.append(f"Earnings per share were ${float(e['value']):.2f} in that quarter, {e['phrase']}.")
    deeper = [_num(f"Sales, quarter to {fmt_date(r['period_end'])}", f"{money_words(float(r['value']))}, {r['phrase']}" if r.get("value") is not None and r.get("phrase") else "Not shown",
                   f"Checked by {r['readers'].split(' / ')[0]}" if r.get("readers") else "Held")
              for r in sorted(rev, key=lambda r: r["period_end"], reverse=True)]
    return _step(2, status="ok" if t else "partial", numbers=numbers, sentences=sentences, idea="growth", check=check, deeper=deeper, summary=summary, uncertain=uncertain)


# ── step 3: margins ─────────────────────────────────────────────────────────────────────────────────────────────────────────

MEASURE_NUMBER_LABEL = {"gross": "Kept per $1 of sales", "operating": "Kept as operating profit per $1 of sales", "net": "Kept as profit per $1 of revenue"}


def margin_hold(m: dict, actions: list[dict]) -> tuple[bool, dict | None]:
    """Pure: (hold everything, hold only "three years earlier") for a recorded spin-off, merger or share-exchange acquisition: inside
    the last four quarters the figure mixes two companies; between the two periods the comparison does."""
    from app.services.valuation import drop_renames_explained
    acts = drop_renames_explained(actions)
    now_start = m["now_start"]
    if any(now_start <= a["date"] <= m["now_end"] for a in acts):
        return True, max((a for a in acts if now_start <= a["date"] <= m["now_end"]), key=lambda a: a["date"])
    if m.get("then_end") and any(m["then_end"] - timedelta(days=365) <= a["date"] < now_start for a in acts):
        return False, max((a for a in acts if m["then_end"] - timedelta(days=365) <= a["date"] < now_start), key=lambda a: a["date"])
    return False, None


ACTION_WORDS = {"spin_off": "spun off {name}", "merger": "merged with {name}", "acquisition": "acquired {name}", "rename_merge": "combined with {name}"}


def action_words(a: dict) -> str:
    return ACTION_WORDS.get(a["kind"], "had a corporate action").format(name=short_name(a.get("name")) or "another business") + f" on {fmt_date(a['date'])}"


def step_margins(name: str, m: dict | None, actions: list[dict]) -> dict:
    if not m or not m.get("ok"):
        why = (m or {}).get("reason") or "Its filings do not tag the figures."
        return _step(3, status="absent", absent=cant(name, why[0].upper() + why[1:] + ("" if why.endswith(".") else ".")), idea="margins")
    hold_all, act = margin_hold(m, actions)
    if hold_all:
        return _step(3, status="absent", absent=cant(name, f"It {action_words(act)}, so its last four quarters mix two businesses."), idea="margins")
    now, then = m["now"], m["then"] if not act else None
    measure = m["measure"]
    now_as_of = f"Four quarters to {fmt_date(m['now_end'])}"
    numbers = [_num(MEASURE_NUMBER_LABEL[measure], cents_value(now), now_as_of)]
    if then is not None:
        numbers.append(_num("Three years earlier", cents_value(then), f"Four quarters to {fmt_date(m['then_end'])}"))
    unit = "revenue dollar" if measure == "net" else "sales dollar"
    first = f"{name} {C.kept(now)} each {unit} {m['plain']}"
    if then is not None:
        same = abs(now - then) < C.MARGIN_SAME_POINTS
        first += f", {'about the same as' if same else 'up from' if now > then else 'down from'} {cents(then)} three years earlier."
    else:
        first += "."
    sentences = [first, f"That is its {m['label']}, {now:.1f}%."]
    if act:
        sentences.append(f"Three years earlier is left out because it {action_words(act)} in between.")
    cyclical = C.is_cyclical(now, then)
    check = C.cyclical_check(name, now, then) if cyclical else C.margins_check(name, now, m["plain"], "revenue" if measure == "net" else "sales")
    deeper = [_num("Measure", m["label"].capitalize(), f"From {m['profit_tag']} over {m['revenue_tag']} in its SEC filings"),
              _num("Last four quarters", f"{money_words(m['now_profit'])} kept of {money_words(m['now_revenue'])}", now_as_of)]
    if then is not None and m.get("then_revenue"):
        deeper.append(_num("Three years earlier", f"{money_words(m['then_profit'])} kept of {money_words(m['then_revenue'])}", f"Four quarters to {fmt_date(m['then_end'])}"))
    summary = f"It {C.kept(now)} each {unit} {m['plain']}" + (f", against {cents(then)} three years earlier." if then is not None else ".")
    return _step(3, status="ok" if then is not None else "partial", numbers=numbers, sentences=sentences, idea="cyclical" if cyclical else "margins", check=check,
                 deeper=deeper, summary=summary, uncertain="Where the cycle in its prices turns next." if cyclical else None)


# ── step 4: the stock against the market ───────────────────────────────────────────────────────────────────────────────────

def _points(series: list[tuple[date, float]]) -> list[list]:
    pts = series[::CHART_EVERY]
    if series and pts[-1] != series[-1]:
        pts.append(series[-1])
    return [[d.isoformat(), round(v, 2)] for d, v in pts]


def step_stock(name: str, sector: str | None, stock: list[tuple[date, float]], spy: list[tuple[date, float]], sec: dict | None, moves: list[dict], min_spy_pct: float,
               today: date) -> dict:
    from app.services.walkthrough_data import QUARTER_SESSIONS, STALE_BAR_DAYS, YEAR_SESSIONS, aligned, change
    cal = [d for d, _ in spy[-YEAR_SESSIONS - 1:]]
    if not cal or (today - cal[-1]).days > STALE_BAR_DAYS:
        return _step(4, status="absent", absent=cant(name, "The S&P 500's stored prices are not up to date, so Ivy can't compare against it."), idea="market_vs_company")
    a = aligned(stock, cal)
    if a is None or len(a) < len(cal):
        return _step(4, status="absent", absent=cant(name, "Its stored prices do not cover the past year up to the latest close."), idea="market_vs_company")
    s_series = [(d, a[d]) for d in cal]
    c1, c3 = change(s_series, YEAR_SESSIONS), change(s_series, QUARTER_SESSIONS)
    p1, p3 = change(spy, YEAR_SESSIONS), change(spy, QUARTER_SESSIONS)
    end = cal[-1]
    as_of = f"Close {fmt_date(end)}"
    numbers = [_num(f"{name} over one year", signed(c1[0]), as_of), _num("S&P 500 (SPY) over one year", signed(p1[0]), as_of)]
    first = f"Over the past year {name}'s stock {moved(c1[0])}, while the S&P 500 {moved(p1[0])}"
    if sec:
        first += f" and the median {sector} stock in the index {moved(sec['change_1y'])}"
    sentences = [first + ".", f"Over the last three months it {moved(c3[0])}, against {signed(p3[0])} for the S&P 500."]
    top = next((m for m in moves if m["spy_pct"] is not None), None)
    check = None
    if top:
        whose = f"mostly {name}'s own" if top["owner"] == "company" else "carried mostly by the market"
        sentences.append(f"Its biggest day in the last three months was {signed(top['move_pct'])} on {fmt_date(top['date'])}"
                         + (", around an earnings report" if top["report_day"] else "") + f", when the S&P 500 moved {signed(top['spy_pct'])}, so that move was {whose}.")
        check = C.market_check(name, fmt_date(top["date"]), top["move_pct"], top["spy_pct"], min_spy_pct)
    base = s_series[0][1]
    spy_a = aligned(spy, cal)
    chart = {"kind": "price_vs_market", "as_of": end.isoformat(), "start": cal[0].isoformat(), "series": [
        {"key": "stock", "label": name, "points": _points([(d, v / base * 100) for d, v in s_series])},
        {"key": "spy", "label": "S&P 500 (SPY)", "points": _points([(d, spy_a[d] / spy_a[cal[0]] * 100) for d in cal])}]}
    if sec:
        chart["series"].append({"key": "sector", "label": f"Median {sector} stock", "points": _points(sec["index"])})
    deeper = [_num(f"{name} over three months", signed(c3[0]), as_of), _num("S&P 500 over three months", signed(p3[0]), as_of)]
    if sec:
        deeper += [_num(f"Median {sector} stock over one year", signed(sec["change_1y"]), f"{sec['members']} S&P 500 stocks, {as_of.lower()}"),
                   _num(f"Median {sector} stock over three months", signed(sec["change_3m"]), f"{sec['members']} S&P 500 stocks, {as_of.lower()}")]
    for mv in moves:
        if mv["spy_pct"] is None:
            continue
        deeper.append(_num(f"{fmt_date(mv['date'])}{', report' if mv['report_day'] else ''}", f"{signed(mv['move_pct'])} against the S&P 500's {signed(mv['spy_pct'])}",
                           "Mostly the company" if mv["owner"] == "company" else "Mostly the market"))
    summary = f"Over a year the stock {moved(c1[0])}, against {signed(p1[0])} for the S&P 500."
    return _step(4, status="ok", numbers=numbers, sentences=sentences, idea="market_vs_company", chart=chart, check=check, deeper=deeper, summary=summary)


# ── step 5: valuation ──────────────────────────────────────────────────────────────────────────────────────────────────────

def step_valuation(name: str, sector: str | None, snap: dict | None, series: list[tuple[date, float]], sec_row: dict | None, enabled: bool) -> dict:
    from statistics import median
    if not enabled:
        return _step(5, status="absent", absent=cant(name, PE_IN_REVIEW), idea="pe")
    if not snap:
        return _step(5, status="absent", absent=cant(name, "Its P/E is not on file."), idea="pe")
    status = snap["status"]
    if status == "not_meaningful":
        why = ("Its earnings over the last four quarters are close to zero, so a P/E says little." if snap.get("pe") is not None
               else "It lost money over the last four quarters, so a price-to-earnings ratio has no meaning.")
        return _step(5, status="absent", absent=f"Ivy can't show a P/E for {name}. {why}", idea="pe")
    if status != "ok" or snap.get("pe") is None:
        why = (snap.get("reason") or "").strip()
        why = (why[0].upper() + why[1:] + ("" if why.endswith(".") else ".")) if why and status == "not_meaningful_yet" else "Its latest earnings are not yet in its filings' data."
        return _step(5, status="absent", absent=cant(name, why), idea="pe")
    pe = float(snap["pe"])
    as_of = f"Close {fmt_date(snap['as_of_date'])}, earnings for the four quarters to {fmt_date(snap['window_end'])}"
    numbers = [_num("P/E", f"{pe:.1f}", as_of)]
    sentences = [f"{name}'s stock costs {pe:.1f} times its earnings over the last four quarters."]
    med_stored = float(snap["hist_median"]) if snap.get("hist_median") is not None else None
    chart = check = None
    vals = [v for _, v in series]
    series_ok = bool(vals) and med_stored is not None and abs(round(median(vals), 1) - med_stored) <= PE_MEDIAN_AGREEMENT
    sector_median = float(sec_row["median_pe"]) if sec_row and sec_row.get("shown") and sec_row.get("median_pe") is not None else None
    if series_ok:
        lo, hi = min(vals), max(vals)
        span = f"{fmt_date(series[0][0])} to {fmt_date(series[-1][0])}"
        numbers.append(_num("Its five-year range", f"{lo:.1f} to {hi:.1f}", span))
        sentences.append(f"Over five years its P/E ran from {lo:.1f} to {hi:.1f}, with a median of {med_stored:.1f}, and today's is higher than on "
                         f"{snap['hist_share_above']}% of those trading days.")
        chart = {"kind": "pe_range", "as_of": snap["as_of_date"].isoformat(), "points": _points(series), "median": med_stored, "today": pe,
                 "sector_median": sector_median, "sector": sector if sector_median is not None else None}
    elif med_stored is not None:
        sentences.append(f"Its median P/E over the past five years is {med_stored:.1f}.")
    if sector_median is not None:
        sentences.append(f"The median {sector} stock in the S&P 500 is at {sector_median:.1f}.")
    if sector == "Real Estate":
        sentences.append(REIT_NOTE)
    summary = None
    if med_stored:
        check = C.pe_check(name, pe, med_stored)
        word = C.pe_word(pe, med_stored)
        rel = {"More than usual": "above", "Less than usual": "below", "About the same as usual": "about level with"}[word]
        summary = f"Investors pay {pe:.1f} times its last four quarters' earnings, {rel} its five-year median of {med_stored:.1f}."
    deeper = [_num("Earnings per share, last four quarters", f"${float(snap['trailing_eps']):.2f}", f"Quarters {fmt_date(snap['window_start'])} to {fmt_date(snap['window_end'])}")]
    if med_stored is not None:
        deeper.append(_num("Five-year median P/E", f"{med_stored:.1f}", f"{snap['hist_sessions']} trading days, {fmt_date(snap['hist_first'])} to {fmt_date(snap['hist_last'])}"))
    if sec_row and not sec_row.get("shown"):
        deeper.append(_num(f"Median {sector} P/E", "Not shown", f"Only {sec_row['fresh']} of {sec_row['active']} stocks in the sector have a current P/E"))
    return _step(5, status="ok" if series_ok else "partial", numbers=numbers, sentences=sentences, idea="pe", chart=chart, check=check, deeper=deeper, summary=summary)


# ── step 6: what's coming up ───────────────────────────────────────────────────────────────────────────────────────────────

def step_upcoming(name: str, ne, timing: str | None, implied: dict | None, typical: dict | None, fed_day: date | None) -> dict:
    from app.services.implied_move import implied_move_allowed
    date_ = getattr(ne, "date", None) if ne else None
    conf = getattr(ne, "confirmation", None) if ne else None
    if not date_ and not getattr(ne, "window_start", None) and not typical:
        return _step(6, status="absent", absent=cant(name, "It has no next report date and no report history on file."), idea="report_move")
    numbers, sentences = [], []
    when = TIMING_WORDS.get((timing or "").lower())
    if date_ and conf == "confirmed":
        numbers.append(_num("Next report", day_words(date_), CONFIRMATION_WORDS["confirmed"]))
        sentences.append(f"{name} reports next on {day_words(date_)}" + (f", {when}" if when else "") + ", a date the company has confirmed.")
    elif conf == "expected_window" and ne.window_start:
        numbers.append(_num("Next report", f"{fmt_date(ne.window_start)} to {fmt_date(ne.window_end)}", CONFIRMATION_WORDS["expected_window"]))
        sentences.append(f"{name} has not announced its next report date. From its past reports, it usually reports between {fmt_date(ne.window_start)} and {fmt_date(ne.window_end)}.")
    elif date_:
        numbers.append(_num("Next report", day_words(date_), CONFIRMATION_WORDS.get(conf or "estimated", CONFIRMATION_WORDS["estimated"])))
        sentences.append(f"{name} is expected to report around {day_words(date_)}, a date the company has not confirmed yet.")
    else:
        sentences.append(f"{name} has no next report date on file yet.")
    imp = implied if implied and date_ and implied_move_allowed(conf) else None
    check = None
    if imp and typical:
        word = compare_moves(imp["pct"], typical["pct"])
        cmp_words = {"more than usual": "more than", "less than usual": "less than", "about its usual": "about the same as"}[word]
        numbers.append(_num("Options price a move of", f"±{imp['pct']:.1f}%", f"Options data {fmt_date(imp['chain_date'])}, expiring {fmt_date(imp['expiration'])}"))
        sentences.append(f"Options price a move of about ±{imp['pct']:.1f}% by {fmt_date(imp['expiration'])}, {cmp_words} its typical ±{typical['pct']:.1f}% after a report.")
        check = C.report_move_check(name, imp["pct"], typical["pct"])
    elif typical:
        numbers.append(_num("Typical move after a report", f"±{typical['pct']:.1f}%", f"{typical['n']} reports to {fmt_date(typical['as_of'])}"))
        sentences.append(f"After its past {typical['n']} reports, the stock moved ±{typical['pct']:.1f}% on a typical report day.")
        check = C.typical_move_check(name, typical["pct"])
    if fed_day:
        sentences.append(f"The next Fed rate decision is on {day_words(fed_day)}, a day that can move the whole market.")
    deeper = []
    if typical:
        deeper.append(_num("Typical move after a report", f"±{typical['pct']:.1f}%", f"Average size of the next-day move over {typical['n']} reports to {fmt_date(typical['as_of'])}"))
    if ne and getattr(ne, "note", None) and date_:
        deeper.append(_num("Where the date comes from", CONFIRMATION_WORDS.get(conf or "estimated", "Estimated"), fmt_date(date_)))
    if fed_day:
        deeper.append(_num("Next Fed decision", day_words(fed_day), "Federal Reserve calendar"))
    summary = (f"It reports next on {fmt_date(date_)} ({'confirmed' if conf == 'confirmed' else 'not yet confirmed'})." if date_ else
               f"It usually reports between {fmt_date(ne.window_start)} and {fmt_date(ne.window_end)}." if ne and getattr(ne, "window_start", None) else
               f"It has moved ±{typical['pct']:.1f}% on a typical report day.")
    uncertain = f"How the stock reacts to its report on {fmt_date(date_)}." if date_ else None
    return _step(6, status="ok" if date_ or getattr(ne, "window_start", None) else "partial", numbers=numbers, sentences=sentences, idea="report_move", check=check,
                 deeper=deeper, summary=summary, uncertain=uncertain)


# ── step 7: risks ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def step_risks(name: str, risks: dict | None, merger: dict | None) -> dict:
    """Without the story step's verified sentences, a partial step pointing to the filing; build_walkthroughs fills `story`."""
    if not risks or not risks.get("ok"):
        return _step(7, status="absent", absent=cant(name, _reason((risks or {}).get("reason"), RISK_REASONS, "Its risk factors are not on file.")), idea="risk_factors")
    if predates(merger, risks.get("filed")):
        return _step(7, status="absent", absent=cant(name, f"It merged with {short_name(merger['name'])} on {fmt_date(merger['date'])}, and its last annual report predates the merger."),
                     idea="risk_factors")
    source = {"label": f"Item 1A of its 10-K, filed {fmt_date(risks['filed'])}", "url": risks.get("url")}
    return _step(7, status="partial", sentences=[f"{name} lists what could go wrong in Item 1A of its 10-K, filed {fmt_date(risks['filed'])}."],
                 numbers=[], idea="risk_factors", source=source, summary=None, uncertain="Whether any of the risks it names comes to pass.")


def with_risk_story(step: dict, name: str, risk_sentences: list[dict]) -> dict:
    """Pure: step 7 with the verified risk sentences ([{n, sentence}]) and the check built from the first."""
    if not risk_sentences:
        step["sentences"].append("Ivy's plain summaries of these risks are not checked yet, so read them in the filing.")
        return step
    step["sentences"] = [f"{name} names these among the risks in Item 1A of its 10-K, filed {step['source']['label'].rsplit('filed ', 1)[-1]}."]
    step["risks"] = risk_sentences
    step["status"] = "ok"
    step["check"] = C.risk_check(name, risk_sentences[0]["sentence"])
    step["summary"] = f"Its annual report names risks, among them that {risk_sentences[0]['sentence'][0].lower()}{risk_sentences[0]['sentence'][1:]}"
    return step


# ── summary, compare row, fingerprints ─────────────────────────────────────────────────────────────────────────────────────

def summary(name: str, steps: list[dict]) -> dict:
    known = []
    for s in steps:
        if s["status"] == "absent" or not s.get("summary"):
            known.append({"n": s["n"], "line": f"Not shown for {name} yet ({s['question'][0].lower()}{s['question'][1:].rstrip('?')}).", "shown": False})
        else:
            known.append({"n": s["n"], "line": s["summary"], "shown": True})
    uncertain = [s["uncertain"] for s in steps if s.get("uncertain") and s["status"] != "absent"]
    concepts = []
    for s in steps:
        idea = s.get("idea")
        if idea and s["status"] != "absent" and idea["concept"] not in [c["concept"] for c in concepts]:
            concepts.append({"concept": idea["concept"], "title": idea["title"]})
    return {"known": known, "uncertain": uncertain, "concepts": concepts, "closing": CLOSING_LINE}


def compare_row(name: str, symbol: str, steps: list[dict], segments: dict | None, growth_ttm: float | None, margins: dict | None, stock_1y: float | None,
                pe: float | None, next_date: date | None, next_confirmed: bool) -> dict:
    """The seven Compare rows for one stock, from the same figures as its walkthrough (None where its walkthrough shows none)."""
    by = {s["n"]: s for s in steps}
    seg_ok = by[1]["status"] != "absent" and segments and segments.get("ok") and by[1]["numbers"]
    m_ok = by[3]["status"] != "absent" and margins and margins.get("ok")
    return {"symbol": symbol, "name": name, "rows": {
        "sells": {"value": f"{segments['segments'][0]['label']}, {segments['segments'][0]['share']:.0f}% of sales", "as_of": by[1]["numbers"][0]["as_of"]} if seg_ok else None,
        "growth": {"value": signed(growth_ttm), "as_of": by[2]["numbers"][-1]["as_of"]} if growth_ttm is not None and by[2]["status"] == "ok" else None,
        "keeps_now": {"value": cents_value(margins["now"]), "as_of": by[3]["numbers"][0]["as_of"], "measure": margins["label"]} if m_ok else None,
        "keeps_then": {"value": cents_value(margins["then"]), "as_of": by[3]["numbers"][1]["as_of"], "measure": margins["label"]} if m_ok and len(by[3]["numbers"]) > 1 else None,
        "stock_1y": {"value": signed(stock_1y), "as_of": by[4]["numbers"][0]["as_of"]} if stock_1y is not None and by[4]["status"] != "absent" else None,
        "pe": {"value": f"{pe:.1f}", "as_of": by[5]["numbers"][0]["as_of"]} if pe is not None and by[5]["status"] != "absent" else None,
        "next_report": {"value": fmt_date(next_date), "as_of": "Confirmed by the company" if next_confirmed else "Not yet confirmed"} if next_date else None,
    }}


COMPARE_ROWS = [("sells", "What it sells most"), ("growth", "Sales growth, last four quarters"), ("keeps_now", "Keeps per $1 now"),
                ("keeps_then", "Keeps per $1 three years earlier"), ("stock_1y", "Stock over one year"), ("pe", "P/E"), ("next_report", "Next report")]
COMPARE_IDEA = ("Comparing", "Side by side works best on the same measures over the same periods. A rival in the same industry shows what is normal for the business, and a familiar giant gives you a ruler you already know.")
COMPARE_MISSING = "Not shown"


def fingerprint(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:32]


def steps_shown(steps: list[dict]) -> int:
    return sum(1 for s in steps if s["status"] != "absent")
