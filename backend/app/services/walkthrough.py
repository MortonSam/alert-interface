"""Ivy's stock walkthrough: seven steps that teach a newcomer to read one stock, rebuilt nightly (scripts/build_walkthroughs).

Every sentence here that states a number is built by rule from stored, dated data (services/walkthrough_data gathers it); the
model only adds at most one story sentence per step, the summary's plain line on what the company does, and step 7's risk
sentences, through services/walkthrough_story, which verifies each. Quick checks come from services/walkthrough_checks. A step
without trustworthy data says so in one line, and the summary names the gap and why. Wording lives in this module's constants and
the step builders, and every visible string is listed in backend/ops/reports/wording_ivy_walkthrough_2026-10-19.md for approval.

Quarters carry the company's own fiscal names (services/fiscal_periods). Figures carry thousands separators and a true minus
sign; sentences state changes in words ("rose 1.6%"), never with a plus sign.

Payload of a step: {n, key, question, status ("ok" | "partial" | "absent"), absent (the one honest line, or None), numbers
[{label, value, as_of}], sentences [rule-built], story (filled by the story step), idea {concept, title, text}, chart, check,
deeper [{label, value, as_of}], source {label, url}, summary (one takeaway line for the summary screen), gap (what the summary
lists as uncertain, or None), fact (this stock's figure for its concept, for the line that compares two stocks once the
concept is known: {concept, measure, lead, short, tail}), point (the step's headline figure in words, for step 7's check),
cell (Compare's figures by measure: {measure: {value, as_of, end}})}.

Every company's sales are called "revenue" (noun_for; Sam, 2026-11-04). A ticker page offers the walkthrough only
when at least ENTRY_MIN_STEPS steps show data (routers/walkthrough serves `entry`).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from app.services.briefing import description_text, fmt_date, short_name
from app.services.fiscal_periods import cap, four_label, quarter, quarter_label, quarter_name, through, year
from app.services import walkthrough_checks as C
from app.services.walkthrough_checks import change_noun, kept, moved, num, pct, signed

WALKTHROUGH_VERSION = 6                           # 2 (2026-10-19): fiscal quarter names, checks that combine facts, REITs on FFO, gaps
                                                  # 3 (same day): checks ask what a fact means; Compare on one measure and comparable periods; "revenue" for banks
                                                  # 4 (2026-10-29, Sam's NVDA review): the company's own explanations quoted (walkthrough_quotes); step 4
                                                  #   leads with its industry and gives no market verdict for a stock over INDEX_SHARE_NO_VERDICT of the
                                                  #   index; P/E charts never break (the latest unbroken run); the P/E check fits the company's year;
                                                  #   the next Fed decision is chosen when served; the options line beside the typical move
                                                  # 5 (2026-11-06, Sam's Nov 4 review): "revenue" for every company; step 5 in dollars ("about $28 for
                                                  #   every $1 of profit"), "P/E" named once; step 1 says which split its figures use and follows the
                                                  #   description's breakdown when the 10-K files both
                                                  # 6 (2026-11-10, Sam): step 5's range, median, chart, summary and check read one window, the
                                                  #   continuous recent stretch ("Since {date}, ..."), "five-year" only over five full years;
                                                  #   a real estate company that is not a trust (CBRE, CSGP) gets a margin step
MINUTES = 3                                       # "about 3 minutes", stated on the entry
CHART_EVERY = 5                                   # chart points: every fifth session, plus the last
PE_MEDIAN_AGREEMENT = 0.15                        # the series' median must match the stored five-year median within this (one decimal rounding)
CLOSING_LINE = "Ivy doesn't make buy or sell calls."
REVENUE_INDUSTRY_WORDS = ("Bank", "Insurance", "Reinsurance")    # GICS sub-industries of banks and insurers, which say "revenue", never "sales"
ENTRY_MIN_STEPS = 5                               # a walkthrough is shown only when at least this many of the seven steps show data (Sam, 2026-11-02; 4 before)
COMPARE_PERIOD_DAYS = 120                         # a Compare row is hidden when the two companies' periods end further apart than this
CHART_PAUSE_DAYS = 7                              # sessions further apart than a long weekend: both are kept when a chart is sampled
CHART_GAP_DAYS = 21                               # frontend lib/walkthroughAxis GAP_DAYS: points further apart break the line; no chart is built with one
INDEX_SHARE_NO_VERDICT = 2.0                      # a stock above this percent of the S&P 500's market value is part of the market: step 4 gives no
                                                  # market-or-company verdict for it (Sam, 2026-10-29, NVDA) and compares it with its industry

QUESTIONS = {
    1: "What does it do, and how does it make money?",
    2: "Is the business getting bigger?",
    3: "How much of each revenue dollar does it keep?",
    4: "What has the stock done, and was it the company or the market?",
    5: "Is it expensive?",
    6: "What's coming up?",
    7: "What could go wrong?",
}
KEYS = {1: "business", 2: "growth", 3: "margins", 4: "stock", 5: "valuation", 6: "upcoming", 7: "risks"}
# what the summary's "still uncertain" list calls a step Ivy couldn't show
GAP_TOPIC = {1: "What it does", 2: "Whether its revenue is growing", 3: "How much of each revenue dollar it keeps", 4: "How its stock did against the market",
             5: "How it is valued", 6: "When it reports next", 7: "What could go wrong"}

# "The idea": the concept behind each step, true of any stock. No figure here may be about one company.
IDEAS = {
    "segments": ("Where the money comes from", "A company's annual report, the 10-K, splits its revenue by business segment, the units it is run and reported as, and often also by product or market. The biggest piece is what really drives the business, whatever the company is best known for."),
    "growth": ("Growth", "Growth compares a quarter with the same quarter a year earlier, so seasonal swings cancel out. Revenue growth shows demand. Earnings per share, set beside revenue, shows how much of that growth reaches each share as profit."),
    "margins": ("Margins", "A margin is the slice of each revenue dollar a company keeps. How the slice changes over several years says something about the company's prices and costs. Compare margins within an industry, since a grocer and a software maker run on very different slices."),
    "market_vs_company": ("Market or company", "Every stock moves partly with the whole market and partly on its own news. Comparing it with the S&P 500 and with similar companies separates the two. If they all rose together, it was the market. If it rose alone, it was the company."),
    "pe": ("Price for each $1 of profit", "Divide the share price by the company's earnings per share over the last year and you get what investors pay for each $1 of its profit. The figure says most next to the same company's past and similar companies."),
    "p_ffo": ("Price to FFO", "A real estate trust is valued on funds from operations, or FFO, per share. FFO adds back the depreciation of its buildings, which accounting writes down every year even when the properties hold their value. Price to FFO is the share price divided by the last year's FFO per share, what investors pay for each dollar the properties bring in."),
    "report_move": ("The report move", "An earnings report is when a company tells investors how its last quarter went. The stock's moves after its past reports show what is normal for it, and options prices show how big a move traders expect this time."),
    "risk_factors": ("Risk factors", "Every annual report has a section called Item 1A, Risk Factors, where the company must list what could hurt it. A listed risk is a disclosure, not a prediction, and reading the list tells you what could change the story."),
}
REIT_GROWTH_NOTE = "Real estate trusts are usually judged by funds from operations per share rather than earnings per share, and Ivy doesn't have that figure for this trust yet."
REIT_VALUE_ABSENT = "Real estate trusts are valued on funds from operations (FFO) per share rather than earnings, and its FFO per share is not on file yet."
GROWTH_IN_REVIEW = "Growth figures are still being checked and are not shown on this site until they pass."
PE_IN_REVIEW = "What investors pay for each $1 of profit (the P/E) is still being checked and isn't shown on this site until it passes."
SEGMENT_REASONS = {
    "no 10-K": ("There is no annual report (10-K) on file at the SEC.", "no annual report on file"),
    "no full fiscal year": ("Its annual report's data has no full fiscal year.", "its annual report has no full year"),
    "do not add up": ("The revenue splits in its annual report do not add up to its total revenue, so Ivy doesn't show them.", "its revenue splits don't add up to its total"),
    "no revenue split": ("Its annual report does not split its revenue by business segment or by product.", "its annual report has no split"),
    "no XBRL instance": ("Its annual report has no machine-readable figures.", "its annual report has no machine-readable figures"),
}
RISK_REASONS = {
    "no 10-K": ("There is no annual report (10-K) on file at the SEC.", "no annual report on file"),
    "could not be found": ("Ivy couldn't find the risk factors section in its annual report.", "its risk section couldn't be found"),
    "could not be read": ("Ivy couldn't read the risk factors in its annual report.", "its risk section couldn't be read"),
}
MARGIN_GAPS = (("real estate", "not measured for real estate trusts"), ("four recent", "its filings lack four recent quarters"),
               ("band", "the figure failed a sanity check"), ("outside", "the figure failed a sanity check"))
CONFIRMATION_WORDS = {"confirmed": "Confirmed by the company", "estimated": "Estimated, not confirmed", "expected_unconfirmed": "Expected, not confirmed",
                      "expected_window": "Expected window from past reports"}
TIMING_WORDS = {"bmo": "before the market opens", "amc": "after the market closes"}


# ── formatting ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def money_words(x: float) -> str:
    """"$133.2 billion", "$1.4 trillion", "$850.0 million", "−$2.1 billion": one decimal, the unit in words."""
    sign = "−" if x < 0 else ""
    for unit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(x) >= unit:
            return f"{sign}${abs(x) / unit:,.1f} {word}"
    return f"{sign}${abs(x):,.0f}"


def per_dollar(x: float) -> str:
    """What investors pay for $1 of profit, as a visitor reads it (Sam, 2026-11-04: "paying about $28 for every $1 of profit"):
    whole dollars from $10, one decimal below ("$7.9")."""
    return f"${x:,.0f}" if x >= 10 else f"${x:,.1f}"


def dollars(x: float) -> str:
    """"$32.87", "−$0.12"."""
    return f"{'−' if x < 0 else ''}${abs(x):,.2f}"


def cents(x: float) -> str:
    """In a sentence: "81¢", "a loss of 9¢"."""
    return f"{round(x)}¢" if round(x) >= 0 else f"a loss of {abs(round(x))}¢"


def cents_value(x: float) -> str:
    """As a displayed figure: "81¢", "−9¢"."""
    return f"{round(x)}¢" if round(x) >= 0 else f"−{abs(round(x))}¢"


def change_phrase(g: float | None, stored: str | None) -> str:
    """"up 1,061.5% from a year earlier", "down 3.7% ...", "unchanged from a year earlier"; a change in words (a loss that
    narrowed, a swing to a profit) keeps the stored phrase, which carries no figure."""
    if g is None:
        return stored or "with no year-earlier comparison"
    if round(g, 1) == 0:
        return "unchanged from a year earlier"
    return f"{'up' if g > 0 else 'down'} {pct(g)} from a year earlier"


def grew(g: float, noun: str = "revenue") -> str:
    return "grew" if round(g, 1) > 0 else "shrank" if round(g, 1) < 0 else ("was" if noun == "revenue" else "were") + " unchanged"


def day_words(d: date) -> str:
    return d.strftime("%a, ") + fmt_date(d)


def iso_dates(text: str) -> str:
    """Pure: "2026-06-29" written "Jun 29, 2026" (a stored reason carries ISO dates; the site never shows them)."""
    import re
    return re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: fmt_date(date(int(m[1]), int(m[2]), int(m[3]))), text)


def is_reit(sector: str | None, industry: str | None) -> bool:
    """Pure: a real estate trust (margins.is_trust, the one rule): FFO in place of earnings, no margin. CBRE and CoStar are not."""
    from app.services.margins import is_trust
    return is_trust(sector, industry)


def noun_for(industry: str | None) -> str:
    """Pure: "revenue", for every company (Sam, 2026-11-04: "revenue" instead of "sales" everywhere in the walkthrough; banks and
    insurers alone said "revenue" before). The `noun` plumbing stays so a wording change is one line."""
    return "revenue"


def each_unit(noun: str) -> str:
    return "revenue dollar" if noun == "revenue" else "sales dollar"


def question_for(n: int, noun: str) -> str:
    return "How much of each revenue dollar does it keep?" if n == 3 and noun == "revenue" else QUESTIONS[n]


def gap_topic(n: int, noun: str) -> str:
    if noun == "revenue":
        return {2: "Whether its revenue is growing", 3: "How much of each revenue dollar it keeps"}.get(n, GAP_TOPIC[n])
    return GAP_TOPIC[n]


def _num(label: str, value: str, as_of: str) -> dict:
    return {"label": label, "value": value, "as_of": as_of}


def _step(n: int, *, status: str, numbers=None, sentences=None, idea: str | None = None, absent: str | None = None, chart=None, check=None,
          deeper=None, source=None, summary: str | None = None, gap: str | None = None, fact: dict | None = None, point: str | None = None,
          cell=None, noun: str = "revenue") -> dict:
    title, text = IDEAS[idea] if idea else (None, None)
    if text and noun == "revenue":
        text = text.replace("Sales", "Revenue").replace("sales", "revenue")
    return {"n": n, "key": KEYS[n], "question": question_for(n, noun), "status": status, "absent": absent, "numbers": numbers or [], "sentences": sentences or [],
            "story": None, "idea": {"concept": idea, "title": title, "text": text} if idea else None, "chart": chart, "check": check,
            "deeper": deeper or [], "source": source, "summary": summary, "gap": f"{gap_topic(n, noun)} ({gap})" if gap else None, "fact": fact,
            "point": point, "cell": cell}


def _absent(n: int, name: str, why: str, gap: str, idea: str, noun: str = "revenue") -> dict:
    return _step(n, status="absent", absent=cant(name, why), idea=idea, gap=gap, noun=noun)


def cant(name: str, why: str) -> str:
    return f"Ivy can't show this for {name} yet. {why}"


def _reason(raw: str | None, table: dict[str, tuple[str, str]], fallback: tuple[str, str]) -> tuple[str, str]:
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

# what a split's figures say they are (Sam, 2026-11-06): a split by product, market or platform is never called "segments"
SPLIT_WORDS = {"business segment": "by business segment", "product or service": "by product and market"}


def mentions(text: str | None, first: list[dict], second: list[dict]) -> tuple[int, int]:
    """Pure: how many of each split's names the description names (case-insensitive, whole words, "&" read as "and"). Longer names
    are matched first and blanked out, so "Compute" never counts inside "Compute and Networking"."""
    import re
    norm = lambda x: re.sub(r"\s+", " ", re.sub(r"\s*&\s*", " and ", (x or "").lower()))     # "Compute & Networking" is "Compute and Networking"
    t = norm(text)
    found = [0, 0]
    names = sorted(((norm(g["label"]), side) for side, segs in enumerate((first, second)) for g in segs if g.get("label")), key=lambda x: -len(x[0]))
    for name, side in names:
        pat = r"(?<![a-z])" + re.escape(name) + r"(?![a-z])"
        if re.search(pat, t):
            found[side] += 1
            t = re.sub(pat, " ", t)
    return found[0], found[1]


def own_names(text: str | None, segs: list[dict]) -> str | None:
    """Pure: the description with each split name the filing writes with "&" written the filing's way (Sam, 2026-11-10: JPM's note
    says "Commercial and Investment Bank" where its 10-K and the figures below it say "Commercial & Investment Bank")."""
    import re
    if not text:
        return text
    for g in segs:
        label = g.get("label") or ""
        if "&" in label:
            words = r"\s+and\s+".join(re.escape(part.strip()) for part in label.split("&"))
            text = re.sub(r"(?<![A-Za-z])" + words + r"(?![A-Za-z])", label, text)
    return text


def split_for(segments: dict, desc: str | None) -> tuple[dict, dict | None]:
    """Pure: (the split step 1 shows, the other one or None). When the 10-K splits revenue both by business segment and by product
    and market, the figures follow the breakdown the description names more of; a tie keeps the reader's first (segments.AXES)."""
    other = segments.get("other")
    if other:
        mine, theirs = mentions(desc, segments["segments"], other["segments"])
        if theirs > mine:
            return ({**segments, **other, "other": None},
                    {k: segments[k] for k in ("axis", "axis_label", "tag", "total", "segments")})
    return segments, other


def nouned(text: str, noun: str) -> str:
    """Pure: a stored reason's "sales" said as "revenue" for a bank or an insurer."""
    return text.replace("sales", "revenue") if noun == "revenue" else text


def step_business(name: str, profile: dict | None, segments: dict | None, merger: dict | None, periods: dict | None = None, noun: str = "revenue",
                  note: dict | None = None) -> dict:
    """Step 1 has no quick check. Its description is the served research note's own "what they do", word for word (Sam, 2026-11-03;
    note: {text, written}); only a stock with no served note falls back to the vendor's company description, which the story step's
    verified plain line on what the company does then replaces (walkthrough_story.apply; "described" marks that fallback)."""
    from_note = bool(note and note.get("text"))
    desc = note["text"] if from_note else description_text((profile or {}).get("short_description"))
    profile_ok = bool(desc) and (from_note or not predates(merger, (profile or {}).get("latest_filing_date")))
    seg_ok = bool(segments and segments.get("ok")) and not predates(merger, segments.get("filed"))
    Noun = cap(noun)
    if not profile_ok and not seg_ok:
        if merger and (desc or (segments and segments.get("ok"))):
            why = (f"It merged with {short_name(merger['name'])} on {fmt_date(merger['date'])}, and its last annual report and company description both describe the business before the merger.",
                   "it merged after its last annual report")
        else:
            why = _reason((segments or {}).get("reason"), SEGMENT_REASONS, ("Its company description and revenue split are not on file.", "no description or revenue split on file"))
        return _absent(1, name, nouned(why[0], noun), nouned(why[1], noun), "segments", noun)
    sentences, numbers, deeper = [], [], []
    as_of_profile = (profile or {}).get("fetched_at")
    if profile_ok:
        if seg_ok:      # the company's own punctuation for its split names, as the figures below write them
            desc = own_names(desc, segments["segments"] + ((segments.get("other") or {}).get("segments") or []))
        sentences.append(desc)
    source = fact = point = cell = gap = None
    summary = None
    if seg_ok:
        shown, other = split_for(segments, desc if profile_ok else None)
        segs, total = shown["segments"], shown["total"]
        by = SPLIT_WORDS.get(shown.get("axis_label"), "by line")
        top = segs[0]
        period = year(periods, segments["end"])
        as_of = f"{cap(period.removeprefix('the '))}, 10-K filed {fmt_date(segments['filed'])}"
        numbers = [_num(f"{Noun} in its last fiscal year", money_words(total), as_of), _num(f"From {top['label']}, {by}", pct(top["share"]), as_of)]
        sentences.append(f"Split {by}, its biggest line is {top['label']}, at {pct(top['share'])} of {money_words(total)} in {period}.")
        if len(segs) > 1:
            sentences.append(f"Next comes {segs[1]['label']} at {pct(segs[1]['share'])}.")
        deeper = [_num(f"{g['label']} ({by})", f"{pct(g['share'])} ({money_words(g['value'])})", as_of) for g in segs]
        if other:
            o = other["segments"][0]
            deeper.append(_num(f"Its 10-K also splits {noun} {SPLIT_WORDS.get(other.get('axis_label'), 'another way')}",
                               f"{o['label']}, {pct(o['share'])}", as_of))
        source = {"label": f"10-K filed {fmt_date(segments['filed'])}", "url": segments.get("url")}
        summary = f"Split {by}, its biggest line, {top['label']}, brought in {pct(top['share'])} of its {noun} in {period}."
        fact = {"concept": "segments", "measure": "segments", "lead": f"{name}'s biggest line, {top['label']}, brought in {pct(top['share'])} of its {noun}",
                "short": f"{name}'s, {top['label']}, brought in {pct(top['share'])}", "tail": f"in {period}"}
        point = f"The {pct(top['share'])} of its {noun} from {top['label']}"
        cell = {"share": {"value": f"{top['label']}, {top['share']:,.0f}% of {noun}", "as_of": f"{as_of}, {by}", "end": str(segments["end"])}}
    else:
        if merger and segments and segments.get("ok"):
            why = (merger_line(merger, "its last annual report"), "it merged after its last annual report")
        else:
            why = _reason((segments or {}).get("reason"), SEGMENT_REASONS, ("Its revenue split is not on file.", "no split on file"))
        sentences.append(f"Ivy can't split {name}'s {noun} yet. {nouned(why[0], noun)}")
        gap = nouned(why[1], noun)
        summary = desc        # until the story step's plain line on what it does replaces it
    if from_note:
        deeper.append(_num("Company description", "Ivy's research note", f"Written {fmt_date(note['written'])}" if note.get("written") else "Ivy's research note"))
    elif profile_ok and as_of_profile:
        deeper.append(_num("Company description", "Intrinio company profile", f"Fetched {fmt_date(as_of_profile.date() if hasattr(as_of_profile, 'date') else as_of_profile)}"))
    st = _step(1, status="ok" if (profile_ok and seg_ok) else "partial", numbers=numbers, sentences=sentences, idea="segments",
               deeper=deeper, source=source, summary=summary, fact=fact, point=point, cell=cell, noun=noun)
    st["described"] = profile_ok and not from_note      # only the vendor's description is replaced by the story's plain line
    st["from_note"] = from_note
    if gap:
        st["gap"] = f"How its {noun} {'splits' if noun == 'revenue' else 'split'} by line ({gap})"
    return st


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


def step_growth(name: str, rows: list[dict] | None, sector: str | None, enabled: bool, periods: dict | None = None, reit: bool = False,
                ffo: dict | None = None, noun: str = "revenue", filing: dict | None = None) -> dict:
    if not enabled:
        return _absent(2, name, GROWTH_IN_REVIEW, "figures still being checked", "growth", noun)
    Noun = cap(noun)
    were = "was" if noun == "revenue" else "were"
    rev = [r for r in rows or [] if r["metric"] == "revenue"]
    eps = {r["period_end"]: r for r in rows or [] if r["metric"] == "eps"}
    newest = max(rev, key=lambda r: r["period_end"], default=None)
    agreed = [r for r in rev if not r.get("held_reason") and r.get("value") is not None and (r.get("growth_pct") is not None or r.get("phrase"))]
    latest = max(agreed, key=lambda r: r["period_end"], default=None)     # the newest quarter both readers agree on (it carries its own date)
    if newest and newest.get("held_reason"):
        return _absent(2, name, f"{iso_dates(newest['held_reason'])}.", "its latest quarter is held for a corporate action", "growth", noun)
    if not latest or (filing and filing["period_end"] > latest["period_end"] + timedelta(days=SAME_QUARTER_DAYS)):
        # the readers do not agree (or agree only on an older quarter): the SEC filing's own figure, labelled as the filing's (Sam, 2026-11-10)
        if filing and filing.get("value") is not None:
            return step_growth_filing(name, filing, periods, noun)
        return _absent(2, name, "Its filings and its earnings releases do not yet agree on these figures.", "its filings and earnings releases don't agree yet", "growth", noun)
    end = latest["period_end"]
    g = float(latest["growth_pct"]) if latest.get("growth_pct") is not None else None
    q = quarter(periods, end)
    qname = quarter_name(periods, end) or f"the quarter ended {fmt_date(end)}"
    numbers = [_num(f"{Noun} against a year earlier", signed(g) if g is not None else latest["phrase"], quarter_label(periods, end))]
    sentences = [f"In {q}, {name}'s {noun} {were} {money_words(float(latest['value']))}, {change_phrase(g, latest.get('phrase'))}."]
    t = ttm_growth(rev)
    summary = None
    cell: dict = {}
    if t:
        now, before, tp, t_end = t
        numbers.append(_num(f"{Noun}, last four quarters against the four before", signed(tp), four_label(periods, t_end)))
        sentences.append(f"Over the last four quarters, {through(periods, t_end)}, {noun} came to {money_words(now)}, {'up' if tp >= 0 else 'down'} {pct(tp)} on the four quarters before.")
        summary = f"Its {noun} {moved(tp)} over the last four quarters, {through(periods, t_end)}, against the four before."
        cell["ttm"] = {"value": signed(tp), "as_of": f"{four_label(periods, t_end)}, against the four before", "end": str(t_end)}
    elif g is not None:
        summary = f"Its {noun} {moved(g)} in {qname} against a year earlier."
    else:
        summary = f"Its {noun} in {qname} {were} {latest['phrase']}."
    if g is not None:
        cell["quarter"] = {"value": signed(g), "as_of": f"{quarter_label(periods, end)}, against a year earlier", "end": str(end)}
    per_share = per_share_pct = None
    if reit:
        f = (ffo or {}).get("latest")
        if f and f["end"] == end and f.get("growth_pct") is not None:
            per_share, per_share_pct = "FFO per share", f["growth_pct"]
            sentences.append(f"FFO per share was {dollars(f['value'])} in that quarter, {change_phrase(f['growth_pct'], None)}.")
        else:
            sentences.append(REIT_GROWTH_NOTE)
    elif end in eps and eps[end].get("value") is not None and not eps[end].get("held_reason"):
        e = eps[end]
        eg = float(e["growth_pct"]) if e.get("growth_pct") is not None else None
        sentences.append(f"Earnings per share were {dollars(float(e['value']))} in that quarter, {change_phrase(eg, e.get('phrase'))}.")
        if eg is not None:
            per_share, per_share_pct = "earnings per share", eg
    check = C.growth_check(name, g, qname, per_share_pct, per_share or "earnings per share", noun)
    deeper = [_num(f"{Noun}, {quarter_name(periods, r['period_end']) or 'quarter'}",
                   f"{money_words(float(r['value']))}, {change_phrase(float(r['growth_pct']) if r.get('growth_pct') is not None else None, r.get('phrase'))}"
                   if r.get("value") is not None and (r.get("phrase") or r.get("growth_pct") is not None) else "Not shown",
                   f"Ended {fmt_date(r['period_end'])}, " + (f"checked {readers_words(r['readers'])}" if r.get("readers") else "held"))
              for r in sorted(rev, key=lambda r: r["period_end"], reverse=True)]
    fact = point = None
    if g is not None:
        fact = {"concept": "growth", "measure": "sales_yoy", "lead": f"{name}'s {noun} {grew(g, noun)} {pct(g)} from a year earlier", "short": f"{name}'s {grew(g, noun)} {pct(g)}",
                "tail": f"in {qname}"}
        point = f"The {pct(g)} {'rise' if g >= 0 else 'fall'} in its {noun} in {qname}"
    st = _step(2, status="ok" if t else "partial", numbers=numbers, sentences=sentences, idea="growth", check=check, deeper=deeper, summary=summary,
               fact=fact, point=point, cell=cell or None, noun=noun)
    return st


def step_growth_filing(name: str, f: dict, periods: dict | None, noun: str = "revenue") -> dict:
    """Step 2 from the SEC filing alone (growth.filing_growth): the quarter's revenue against the same quarter a year earlier, each as
    first filed, every figure labelled as the filing's. No quick check: the earnings release reads the quarter differently."""
    end = f["period_end"]
    g = float(f["growth_pct"]) if f.get("growth_pct") is not None else None
    q = quarter(periods, end)
    qname = quarter_name(periods, end) or f"the quarter ended {fmt_date(end)}"
    form = f.get("form") or "10-Q"
    as_of = f"{quarter_label(periods, end)}, from its {form} filed {fmt_date(f['filed'])}" if f.get("filed") else f"{quarter_label(periods, end)}, from its {form}"
    numbers = [_num(f"{cap(noun)} against a year earlier, as filed", signed(g) if g is not None else f["phrase"], as_of)]
    sentences = [f"In {q}, {name}'s {noun} was {money_words(float(f['value']))}, {change_phrase(g, f.get('phrase'))}, as its {form} reports it.",
                 "Its earnings release reads the quarter differently, so these figures are the filing's alone."]
    summary = f"Its {noun} {moved(g)} in {qname} against a year earlier, as its {form} reports it." if g is not None else f"Its {noun} in {qname} {f['phrase']}, as its {form} reports it."
    deeper = [_num(f"{cap(noun)}, {quarter_name(periods, end) or 'quarter'}", money_words(float(f["value"])), as_of),
              _num(f"{cap(noun)}, a year earlier", money_words(float(f["year_ago_value"])), f"Ended {fmt_date(f['year_ago_end'])}, as first filed")]
    cell = {"quarter": {"value": signed(g), "as_of": f"{as_of}, against a year earlier", "end": str(end)}} if g is not None else None
    fact = point = None
    if g is not None:
        fact = {"concept": "growth", "measure": "sales_yoy", "lead": f"{name}'s {noun} {grew(g, noun)} {pct(g)} from a year earlier", "short": f"{name}'s {grew(g, noun)} {pct(g)}",
                "tail": f"in {qname}"}
        point = f"The {pct(g)} {'rise' if g >= 0 else 'fall'} in its {noun} in {qname}"
    st = _step(2, status="partial", numbers=numbers, sentences=sentences, idea="growth", deeper=deeper, summary=summary, fact=fact,
               point=point, cell=cell, noun=noun)
    st["from_filing"] = True
    return st


# ── step 3: margins ─────────────────────────────────────────────────────────────────────────────────────────────────────────

MEASURE_NUMBER_LABEL = {"gross": "Kept per $1 of revenue", "operating": "Kept as operating profit per $1 of revenue", "net": "Kept as profit per $1 of revenue"}


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


def margin_gap(why: str) -> str:
    low = why.lower()
    return next((g for k, g in MARGIN_GAPS if k in low), "its filings lack the figures")


def _iso(d) -> date | None:
    return d if isinstance(d, date) or d is None else date.fromisoformat(str(d)[:10])


def margin_cells(m: dict, periods: dict | None, keep_then: bool) -> dict:
    """Compare's margin cells on every measure the filings support: {"keeps_now": {measure: cell}, "keeps_then": {measure: cell}}."""
    out: dict = {"keeps_now": {}, "keeps_then": {}}
    for measure, r in (m.get("by_measure") or {m["measure"]: m}).items():
        now_end, then_end = _iso(r["now_end"]), _iso(r.get("then_end"))
        out["keeps_now"][measure] = {"value": cents_value(r["now"]), "as_of": four_label(periods, now_end), "end": str(now_end)}
        if keep_then and r.get("then") is not None and then_end:
            out["keeps_then"][measure] = {"value": cents_value(r["then"]), "as_of": f"Four quarters {through(periods, then_end)}", "end": str(then_end)}
    return out


PROFIT_LINE = {"gross": "Gross profit", "operating": "Operating income", "net": "Net income"}   # step 3's Go deeper, never a tag name


def readers_words(readers: str) -> str:
    """Pure: which readers agreed on a growth figure, as a visitor reads it (Sam, 2026-11-10: no "XBRL" or tag name on screen):
    "against the filing and the earnings release", "against the filing as first filed and as restated a year later"."""
    first = readers.split(" / ")[0]
    if "restated" in first:
        return "against the filing as first filed and as restated a year later"
    if "release" in first:
        return "against the filing and the earnings release"
    return "against the filing"


def step_margins(name: str, m: dict | None, actions: list[dict], periods: dict | None = None, noun: str = "revenue") -> dict:
    if not m or not m.get("ok"):
        why = nouned((m or {}).get("reason") or "Its filings do not tag the figures.", noun)     # a stored reason says "revenue" too
        return _absent(3, name, why[0].upper() + why[1:] + ("" if why.endswith(".") else "."), margin_gap(why), "margins", noun)
    hold_all, act = margin_hold(m, actions)
    if hold_all:
        return _absent(3, name, f"It {action_words(act)}, so its last four quarters mix two businesses.", "a merger or spin-off inside the last four quarters", "margins", noun)
    now, then = m["now"], m["then"] if not act else None
    measure = m["measure"]
    now_as_of = four_label(periods, m["now_end"])
    numbers = [_num(MEASURE_NUMBER_LABEL[measure], cents_value(now), now_as_of)]
    if then is not None:
        numbers.append(_num("Three years earlier", cents_value(then), f"Four quarters {through(periods, m['then_end'])}"))
    unit = "revenue dollar" if measure == "net" or noun == "revenue" else "sales dollar"
    first = f"{name} {kept(now)} each {unit} {m['plain']}"
    first += f", against {cents(then)} three years earlier." if then is not None else "."
    sentences = [first, f"That is its {m['label']}, {num(now)}%."]
    if act:
        sentences.append(f"Three years earlier is left out because it {action_words(act)} in between.")
    check = C.margins_check(name, now, then, unit)
    deeper = [_num("Measure", m["label"].capitalize(), f"{PROFIT_LINE[m['measure']]} over revenue, from its SEC filings"),
              _num("Last four quarters", f"{money_words(m['now_profit'])} kept of {money_words(m['now_revenue'])}", now_as_of)]
    if then is not None and m.get("then_revenue"):
        deeper.append(_num("Three years earlier", f"{money_words(m['then_profit'])} kept of {money_words(m['then_revenue'])}", f"Four quarters {through(periods, m['then_end'])}"))
    summary = f"It {kept(now)} each {unit} {m['plain']}" + (f", against {cents(then)} three years earlier." if then is not None else ".")
    short_kept = f"keeps {round(now)}¢" if round(now) >= 0 else f"loses {abs(round(now))}¢"
    fact = {"concept": "margins", "measure": measure, "lead": f"{name} {kept(now)} each {unit} {m['plain']}", "short": f"{name} {short_kept}",
            "tail": f"in the four quarters {through(periods, m['now_end'])}"}
    point = f"The {round(now)}¢ it keeps of each {unit}" if round(now) >= 0 else f"The {abs(round(now))}¢ it loses on each {unit}"
    st = _step(3, status="ok" if then is not None else "partial", numbers=numbers, sentences=sentences, idea="margins", check=check,
               deeper=deeper, summary=summary, fact=fact, point=point, cell=margin_cells(m, periods, keep_then=not act), noun=noun)
    if then is None:
        st["gap"] = "How its margin compares with three years earlier (" + ("a corporate action in between" if act else "no figure for three years earlier") + ")"
    return st


# ── step 4: the stock against the market ───────────────────────────────────────────────────────────────────────────────────

def _points(series: list[tuple[date, float]]) -> list[list]:
    pts = series[::CHART_EVERY]
    if series and pts[-1] != series[-1]:
        pts.append(series[-1])
    return [[d.isoformat(), round(v, 2)] for d, v in pts]


def _window_points(run: list[tuple[date, float]]) -> list[list]:
    """Pure: _points for step 5's window, keeping the sessions on both sides of any pause in it, so sampling every fifth session
    never widens a short pause past CHART_GAP_DAYS and the chart starts where the window does."""
    n = len(run)
    keep = set(range(0, n, CHART_EVERY)) | {n - 1}
    for i in range(n - 1):
        if (run[i + 1][0] - run[i][0]).days > CHART_PAUSE_DAYS:
            keep |= {i, i + 1}
    return [[run[i][0].isoformat(), round(run[i][1], 2)] for i in sorted(keep)]


def index_share(symbol: str, tickers: dict) -> dict | None:
    """Pure: the stock's share of the S&P 500's market value, {pct, as_of}: its stored market value over the sum of every active
    index member's, dated by the oldest stored value among them. None without its own value."""
    me = tickers.get(symbol) or {}
    members = [t for t in tickers.values() if t.get("index_member") and t.get("market_cap")]
    if not me.get("market_cap") or not me.get("index_member") or not members:
        return None
    dates = [t.get("market_cap_updated_at") for t in members if t.get("market_cap_updated_at")]
    as_of = min(dates).date() if dates else None
    return {"pct": round(me["market_cap"] / sum(t["market_cap"] for t in members) * 100, 1), "as_of": as_of, "members": len(members)}


def industry_verdict(stock: float, sector_pct: float) -> str:
    """Pure: "outpaced", "lagged" or "kept pace with" its sector (the median stock of its sector in the index), by walkthrough_checks' closeness rule."""
    return "kept pace with" if C.close(stock, sector_pct) else "outpaced" if stock > sector_pct else "lagged"


def step_stock(name: str, sector: str | None, stock: list[tuple[date, float]], spy: list[tuple[date, float]], sec: dict | None, moves: list[dict], min_spy_pct: float,
               today: date, share: dict | None = None) -> dict:
    """Step 4 leads with the sector (the median stock of its sector in the index, called its sector on screen), then the S&P 500. A stock over
    INDEX_SHARE_NO_VERDICT of the index's market value is part of the market's move: no market-or-company verdict, for the year or a
    day, and its check asks what that share means instead (Sam, 2026-10-29)."""
    from app.services.walkthrough_data import QUARTER_SESSIONS, STALE_BAR_DAYS, YEAR_SESSIONS, aligned, change
    cal = [d for d, _ in spy[-YEAR_SESSIONS - 1:]]
    if not cal or (today - cal[-1]).days > STALE_BAR_DAYS:
        return _absent(4, name, "The S&P 500's prices on file are not up to date, so Ivy can't compare against it.", "the S&P 500's prices are not up to date", "market_vs_company")
    a = aligned(stock, cal)
    if a is None or len(a) < len(cal):
        return _absent(4, name, "Its prices on file do not cover the past year up to the latest close.", "its prices don't cover the past year", "market_vs_company")
    s_series = [(d, a[d]) for d in cal]
    c1, c3 = change(s_series, YEAR_SESSIONS), change(s_series, QUARTER_SESSIONS)
    p1, p3 = change(spy, YEAR_SESSIONS), change(spy, QUARTER_SESSIONS)
    end = cal[-1]
    as_of = f"Close {fmt_date(end)}"
    heavy = bool(share and share["pct"] > INDEX_SHARE_NO_VERDICT)
    numbers = [_num(f"{name} over one year", signed(c1[0]), as_of)]
    if sec:
        numbers.append(_num(f"Median {sector} stock over one year", signed(sec["change_1y"]), f"{sec['members']} S&P 500 stocks, close {fmt_date(end)}"))
    numbers.append(_num("S&P 500 (SPY) over one year", signed(p1[0]), as_of))
    sentences = []
    if sec and heavy:
        sentences.append(f"Over the past year {name}'s stock {moved(c1[0])}, against {change_noun(sec['change_1y'])} for the median {sector} stock in the S&P 500, "
                         f"so it {industry_verdict(c1[0], sec['change_1y'])} its sector.")
    elif sec:
        sentences.append(f"Over the past year {name}'s stock {moved(c1[0])}, against {change_noun(sec['change_1y'])} for the median {sector} stock in the S&P 500 "
                         f"and {change_noun(p1[0])} for the S&P 500 itself.")
    else:
        sentences.append(f"Over the past year {name}'s stock {moved(c1[0])}, while the S&P 500 {moved(p1[0])}.")
    if heavy:
        sentences.append(f"The S&P 500 {moved(p1[0])} over the same year, and {name} makes up {num(share['pct'])}% of the index by market value.")
    sentences.append(f"Over the last three months it {moved(c3[0])}, against {change_noun(p3[0])} for the S&P 500.")
    top = next((m for m in moves if m["spy_pct"] is not None), None)
    if top:
        owner = f"mostly {name}'s own" if top["owner"] == "company" else "carried mostly by the market"
        whose = "" if heavy else f", so that move was {owner}"
        sentences.append(f"Its biggest day in the last three months was {fmt_date(top['date'])}" + (", around an earnings report" if top["report_day"] else "")
                         + f", when it {moved(top['move_pct'])} and the S&P 500 {moved(top['spy_pct'])}{whose}.")
    if heavy:
        check = C.index_share_check(name, share["pct"])
    else:
        check = C.market_check(name, sector, c1[0], sec["change_1y"], p1[0]) if sec else None
    base = s_series[0][1]
    spy_a = aligned(spy, cal)
    chart = {"kind": "price_vs_market", "as_of": end.isoformat(), "start": cal[0].isoformat(), "series": [
        {"key": "stock", "label": name, "points": _points([(d, v / base * 100) for d, v in s_series])},
        {"key": "spy", "label": "S&P 500 (SPY)", "points": _points([(d, spy_a[d] / spy_a[cal[0]] * 100) for d in cal])}]}
    if sec:
        chart["series"].append({"key": "sector", "label": f"Median {sector} stock", "points": _points(sec["index"])})
    deeper = []
    if sec:
        deeper.append(_num(f"Median {sector} stock over three months", signed(sec["change_3m"]), f"{sec['members']} S&P 500 stocks, close {fmt_date(end)}"))
    deeper += [_num(f"{name} over three months", signed(c3[0]), as_of), _num("S&P 500 over three months", signed(p3[0]), as_of)]
    if share:
        deeper.append(_num(f"{name}'s share of the S&P 500", f"{num(share['pct'])}%", f"By market value on file, {share['members']} index stocks"
                           + (f", values as of {fmt_date(share['as_of'])} or later" if share.get("as_of") else "")))
    for mv in moves:
        if mv["spy_pct"] is None:
            continue
        deeper.append(_num(f"{fmt_date(mv['date'])}{', report' if mv['report_day'] else ''}", f"{signed(mv['move_pct'])}, S&P 500 {signed(mv['spy_pct'])}",
                           "" if heavy else "Mostly the company" if mv["owner"] == "company" else "Mostly the market"))
    if sec and heavy:
        summary = (f"Over the year to {fmt_date(end)} the stock {moved(c1[0])}, against {change_noun(sec['change_1y'])} for the median {sector} stock, "
                   f"so it {industry_verdict(c1[0], sec['change_1y'])} its sector.")
    elif sec:
        summary = (f"Over the year to {fmt_date(end)} the stock {moved(c1[0])}, against {change_noun(sec['change_1y'])} for the median {sector} stock and "
                   f"{change_noun(p1[0])} for the S&P 500, so its year was {C.OWNER_SUMMARY[C.year_owner(c1[0], sec['change_1y'], p1[0])]}.")
    else:
        summary = f"Over the year to {fmt_date(end)} the stock {moved(c1[0])}, against {change_noun(p1[0])} for the S&P 500."
    fact = {"concept": "market_vs_company", "measure": "stock_1y", "lead": f"{name}'s stock {moved(c1[0])}", "short": f"{name}'s {moved(c1[0])}",
            "tail": f"over the year to {fmt_date(end)}"}
    point = f"The {pct(c1[0])} {'rise' if c1[0] >= 0 else 'fall'} in its stock over the year"
    st = _step(4, status="ok", numbers=numbers, sentences=sentences, idea="market_vs_company", chart=chart, check=check, deeper=deeper, summary=summary,
               fact=fact, point=point, cell={"close": {"value": signed(c1[0]), "as_of": as_of, "end": str(end)}})
    st["year_pct"] = c1[0]                                 # step 5's check sets the P/E against the stock's year
    return st


# ── step 5: valuation ──────────────────────────────────────────────────────────────────────────────────────────────────────

def runs(series: list[tuple[date, float]], gap_days: int = CHART_GAP_DAYS) -> list[list[tuple[date, float]]]:
    """Pure: the series split wherever two neighbouring points sit more than gap_days apart."""
    out: list[list[tuple[date, float]]] = []
    for d, v in series:
        if out and (d - out[-1][-1][0]).days <= gap_days:
            out[-1].append((d, v))
        else:
            out.append([(d, v)])
    return out


def chart_gaps(chart: dict | None, gap_days: int = CHART_GAP_DAYS) -> list[str]:
    """Pure: every break in a walkthrough chart's lines ("pe_range: 2023-02-22 to 2023-09-21"); a chart is built only without one."""
    if not chart:
        return []
    lines = [("pe", chart["points"])] if chart.get("kind") == "pe_range" else [(sr["key"], sr["points"]) for sr in chart.get("series") or []]
    out = []
    for key, pts in lines:
        days = [date.fromisoformat(str(p[0])[:10]) for p in pts]
        out += [f"{chart.get('kind')} {key}: {a} to {b}" for a, b in zip(days, days[1:]) if (b - a).days > gap_days]
    return out


RANGE_BEFORE = {"over_cap": "they paid more than {cap}", "loss": "it had lost money over four quarters",
                "action": "a merger or spin-off sat inside its four quarters"}
FIVE_YEAR_SLACK_DAYS = 7              # a window that starts within this of five years before its last day counts five full years
RANGE_MIN_SESSIONS = 60               # a stretch shorter than about a quarter is no range: step 5 shows today's figure alone


def _cap() -> str:
    from app.services.valuation import MIN_EARNINGS_YIELD
    return f"${1 / MIN_EARNINGS_YIELD:,.0f}"


def range_window(series: list[tuple[date, float]], left_out: dict) -> dict | None:
    """Pure: step 5's window (Sam, 2026-11-10): the continuous recent stretch of the P/E history, the sessions after the last one
    the history leaves out (a loss, a price over the cap, a corporate action) and after the last break in the series, so "since
    {first}" is true of every session in it. The range, the median, the chart, the summary and the quick check all read this one
    window. {run, first, last, low, high, median, five_year, before, last_gone, last_reason}: five_year only when the window is the whole
    history and starts five years before its last day; before lists why earlier sessions were left out; median is the window's
    own. None for an empty series."""
    from statistics import median
    from app.services.valuation import RANGE_YEARS
    if not series:
        return None
    gone = [d for d in left_out if d <= series[-1][0]]
    last_gone = max(gone, default=None)
    run = [x for x in runs(series)[-1] if last_gone is None or x[0] > last_gone]
    if not run:
        return None
    first, last = run[0][0], run[-1][0]
    vals = [v for _, v in run]
    five = len(run) == len(series) and not gone and (first - (last - timedelta(days=round(365.25 * RANGE_YEARS)))).days <= FIVE_YEAR_SLACK_DAYS
    return {"run": run, "first": first, "last": last, "low": min(vals), "high": max(vals), "median": round(median(vals), 1), "five_year": five,
            "before": [r for r in RANGE_BEFORE if r in {left_out[d] for d in gone}], "last_gone": last_gone,
            "last_reason": left_out[last_gone] if last_gone else None}


def before_words(reasons: list[str]) -> str:
    """Pure: "they paid more than $100 at times", "they paid more than $100 or it had lost money over four quarters at times"."""
    return " or ".join(RANGE_BEFORE[r].format(cap=_cap()) for r in reasons) + " at times"


def range_words(w: dict) -> tuple[str, str, str]:
    """Pure: step 5's range (label, as of, sentence) over range_window's stretch, in Sam's words (2026-11-10): "Since Oct 20, 2023,
    investors have paid between $25 and $68 for each $1 of its profit, and $41 at the median. Before that, they paid more than
    $100 at times." "Over five years" only when five full years are counted."""
    lo, hi, med = per_dollar(w["low"]), per_dollar(w["high"]), per_dollar(w["median"])
    span = f"{len(w['run']):,} trading days, {fmt_date(w['first'])} to {fmt_date(w['last'])}"
    if w["five_year"]:
        return "Its five-year range", span, f"Over five years, investors have paid between {lo} and {hi} for each $1 of its profit, and {med} at the median."
    line = f"Since {fmt_date(w['first'])}, investors have paid between {lo} and {hi} for each $1 of its profit, and {med} at the median."
    if w["before"]:
        line += f" Before that, {before_words(w['before'])}."
    return f"Its range since {fmt_date(w['first'])}", span, line


NO_RANGE_WHY = {"over_cap": "investors paid more than {cap} for each $1 of its profit", "loss": "it had lost money over its last four quarters",
                "action": "a merger or spin-off sat inside its last four quarters"}


def no_range_line(w: dict | None) -> str:
    """Pure: step 5's line when the stretch is shorter than RANGE_MIN_SESSIONS: no range, and why (the last session left out)."""
    if w and w["last_gone"]:
        return f"Ivy has no recent range to set that against yet. As recently as {fmt_date(w['last_gone'])}, {NO_RANGE_WHY[w['last_reason']].format(cap=_cap())}."
    return "Ivy has no recent range to set that against yet."


def step_valuation(name: str, sector: str | None, snap: dict | None, series: list[tuple[date, float]], sec_row: dict | None, enabled: bool,
                   periods: dict | None = None, left_out: dict | None = None, year: dict | None = None) -> dict:
    """The range, its median, the chart, the summary and the quick check all read one window (range_window): five years when five
    full years are counted, otherwise the continuous recent stretch, named by its first day. A stretch shorter than
    RANGE_MIN_SESSIONS shows today's figure alone. year (walkthrough_data.pe_year) lets the check name this company's reason, when
    the day a year earlier sits inside the window."""
    from statistics import median
    if not enabled:
        return _absent(5, name, PE_IN_REVIEW, "P/E figures still being checked", "pe")
    if not snap:
        return _absent(5, name, "What investors pay for each $1 of its profit is not on file.", "no P/E on file", "pe")
    status = snap["status"]
    if status == "not_meaningful":
        lost = snap.get("pe") is None
        why = ("It lost money over the last four quarters, so there is no profit to set the price against." if lost
               else "Its earnings over the last four quarters are close to zero, so the figure would say little.")
        st = _step(5, status="absent", absent=f"Ivy can't show what investors pay for each $1 of {name}'s profit. {why}", idea="pe",
                   gap="it lost money over the last four quarters" if lost else "its earnings are close to zero")
        return st
    if status != "ok" or snap.get("pe") is None:
        why = (snap.get("reason") or "").strip()
        why = (why[0].upper() + why[1:] + ("" if why.endswith(".") else ".")) if why and status == "not_meaningful_yet" else "Its latest earnings are not yet in its filings' data."
        return _absent(5, name, why, "its latest earnings are not yet in its filings", "pe")
    pe = float(snap["pe"])
    as_of = f"Close {fmt_date(snap['as_of_date'])}, earnings over the last four quarters, {through(periods, snap['window_end'])}"
    numbers = [_num("Paid for each $1 of profit", per_dollar(pe), as_of)]
    # "P/E" is named once, here (Sam, 2026-11-04); every other line says it in dollars
    sentences = [f"Investors are paying about {per_dollar(pe)} for every $1 of {name}'s profit over the last four quarters. "
                 f"That figure is the price-to-earnings ratio, or P/E."]
    med_stored = float(snap["hist_median"]) if snap.get("hist_median") is not None else None
    chart = check = None
    vals = [v for _, v in series]
    # the series is the stored history when its median is the stored one; only then is any of it shown
    series_ok = bool(vals) and med_stored is not None and abs(round(median(vals), 1) - med_stored) <= PE_MEDIAN_AGREEMENT
    sector_median = float(sec_row["median_pe"]) if sec_row and sec_row.get("shown") and sec_row.get("median_pe") is not None else None
    w = range_window(series, left_out or {}) if series_ok else None
    ranged = bool(w) and len(w["run"]) >= RANGE_MIN_SESSIONS
    med = since = None
    if ranged:
        med = med_stored if w["five_year"] else w["median"]          # five full years: the stored five-year median itself
        since = None if w["five_year"] else w["first"]
        w = {**w, "median": med}
        label, span, line = range_words(w)
        numbers.append(_num(label, f"{per_dollar(w['low'])} to {per_dollar(w['high'])}", span))
        sentences.append(line)
        pts = _window_points(w["run"])
        chart = {"kind": "pe_range", "as_of": snap["as_of_date"].isoformat(), "points": pts, "median": med, "median_label": C.median_label(since),
                 "today": pe, "sector_median": sector_median, "sector": sector if sector_median is not None else None, "start": w["first"].isoformat()}
        if chart_gaps(chart):
            chart = None                                   # never: the window has no break; a chart with one is not shown
    elif series_ok:
        sentences.append(no_range_line(w))
    if sector_median is not None:
        sentences.append(f"For the median {sector} stock in the S&P 500, they pay {per_dollar(sector_median)}.")
    summary = f"Investors pay about {per_dollar(pe)} for every $1 of its profit over the last four quarters."
    if ranged:
        check = C.pe_check(name, pe, med, year if year and year.get("then") and year["then"] >= w["first"] else None, since)
        rel = {"More than usual": "above", "Less than usual": "below", "About the same as usual": "about level with"}[C.pe_word(pe, med)]
        summary = f"Investors pay about {per_dollar(pe)} for every $1 of its profit over the last four quarters, {rel} {C.median_words(med, since)}."
    deeper = [_num("Earnings per share, last four quarters", dollars(float(snap["trailing_eps"])), f"Four quarters {through(periods, snap['window_end'])}")]
    if ranged:
        own = C.median_label(since).removeprefix("Its ")                       # "Five-year median", "Median since Oct 20, 2023"
        deeper.append(_num(f"{own[0].upper()}{own[1:]}, paid for each $1 of profit", per_dollar(med), span))
    if sec_row and not sec_row.get("shown"):
        deeper.append(_num(f"Median {sector} stock, paid for each $1 of profit", "Not shown", f"Only {sec_row['fresh']} of {sec_row['active']} stocks in the sector have a current figure"))
    fact = {"concept": "pe", "measure": "pe", "lead": f"Investors pay about {per_dollar(pe)} for every $1 of {name}'s profit",
            "short": f"For {name}'s, about {per_dollar(pe)}", "tail": f"at the {fmt_date(snap['as_of_date'])} close"}
    return _step(5, status="ok" if ranged else "partial", numbers=numbers, sentences=sentences, idea="pe", chart=chart, check=check, deeper=deeper, summary=summary,
                 fact=fact, point=f"The {per_dollar(pe)} investors pay for each $1 of its profit", cell={"pe": {"value": per_dollar(pe), "as_of": as_of, "end": str(snap["as_of_date"])}})


LAST_PE_DAYS = 120                    # the last P/E on file stands in for at most this long after its close (step 5, Sam 2026-11-10)


def last_pe_usable(last_ok: dict, missing: dict, today: date) -> bool:
    """Pure: the last P/E on file may stand in while the newest quarter is not in the filings' data: it is recent, and the snapshot
    that has none is missing only for that (a loss or a corporate action is never covered over)."""
    reason = (missing.get("reason") or "").lower()
    newer = "newer than xbrl" in reason or "not yet in" in reason or "not on file" in reason
    return newer and last_ok.get("pe") is not None and (today - last_ok["as_of_date"]).days <= LAST_PE_DAYS


def pe_behind_line(reported: date | None, snap: dict, periods: dict | None) -> str:
    """Pure: step 5's line while it shows the last P/E on file: "Its newest quarter, reported Nov 5, 2026, isn't in its filings' data
    yet; the figures above are as of the Oct 30, 2026 close, with earnings through Q3 2026." """
    when = f", reported {fmt_date(reported)}," if reported else ""
    return (f"Its newest quarter{when} isn't in its filings' data yet; the figures above are as of the {fmt_date(snap['as_of_date'])} close, "
            f"with earnings {through(periods, snap['window_end'])}.")


def step_valuation_reit(name: str, ffo: dict | None, close: dict | None, periods: dict | None = None) -> dict:
    """A real estate trust is never taught P/E: price to FFO per share over the last four quarters, or the honest absence."""
    ttm = (ffo or {}).get("ttm")
    if not ttm or not close or ttm["sum"] <= 0:
        return _absent(5, name, REIT_VALUE_ABSENT, "its FFO per share is not on file yet", "p_ffo")
    x = close["close"] / ttm["sum"]
    as_of = f"Close {fmt_date(close['date'])}, FFO over the last four quarters, {through(periods, ttm['end'])}"
    sentences = [f"{name}'s stock costs {num(x)} times its FFO per share over the last four quarters.",
                 f"Its FFO per share over those quarters came to {dollars(ttm['sum'])}."]
    return _step(5, status="partial", numbers=[_num("Price to FFO", num(x), as_of)], sentences=sentences, idea="p_ffo",
                 deeper=[_num("FFO per share, last four quarters", dollars(ttm["sum"]), four_label(periods, ttm["end"]))],
                 summary=f"Investors pay {num(x)} times its FFO per share over the last four quarters.",
                 fact={"concept": "p_ffo", "measure": "p_ffo", "lead": f"{name}'s price is {num(x)} times its FFO per share", "short": f"{name}'s is {num(x)} times",
                       "tail": f"at the {fmt_date(close['date'])} close"},
                 point=f"Its price of {num(x)} times FFO per share", cell={"p_ffo": {"value": num(x), "as_of": as_of, "end": str(close["date"])}})


# ── step 6: what's coming up ───────────────────────────────────────────────────────────────────────────────────────────────

def step_upcoming(name: str, ne, timing: str | None, implied: dict | None, typical: dict | None, fed_day: date | None = None,
                  ordinary: float | None = None, report_share: dict | None = None) -> dict:
    """The check: report days move the stock k times as much as an ordinary day (ordinary: the mean move on other days, which the
    step's own text never states); what that means for someone holding it through the next report. The next Fed decision is added
    when the step is served (with_fed), so it is never one that has passed; fed_day here is for a build's own report.

    The options line compares like with like (Sam's NVDA review, 2026-11-02): with a confirmed date and the report's own share of the
    move on file (services/report_move.report_move_view, as Ivy's Read states it: report_share {pct, chain_date, verdict}), that
    share is set beside the typical report-day move by the site's one rule; otherwise the options figure is stated with its
    expiration (implied: the straddle through the first expiration after the report) and compared with nothing, since a move
    through an expiration days after the report is not a report-day move."""
    from app.services.implied_move import implied_move_allowed
    date_ = getattr(ne, "date", None) if ne else None
    conf = getattr(ne, "confirmation", None) if ne else None
    if not date_ and not getattr(ne, "window_start", None) and not typical:
        return _absent(6, name, "It has no next report date and no report history on file.", "no report date or history on file", "report_move")
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
    confirmed = bool(date_ and conf == "confirmed" and implied_move_allowed(conf))
    imp = implied if implied and confirmed else None
    share = report_share if report_share and confirmed and report_share.get("pct") is not None else None
    if typical:
        numbers.append(_num("Typical move after a report", f"±{num(typical['pct'])}%", f"{typical['n']} reports to {fmt_date(typical['as_of'])}"))
        sentences.append(f"After its past {typical['n']} reports, the stock moved ±{num(typical['pct'])}% on a typical report day.")
    if share:
        cmp_words = OPTIONS_COMPARISON.get(share.get("verdict")) if typical else None
        numbers.append(_num("Options price for the report itself", f"±{num(share['pct'])}%", f"Options data {fmt_date(share['chain_date'])}"))
        sentences.append(f"Options price a move of about ±{num(share['pct'])}% from the report itself"
                         + (f", {cmp_words} its typical move on a report day." if cmp_words else "."))
    elif imp:
        numbers.append(_num("Options price a move of", f"±{num(imp['pct'])}%", f"Options data {fmt_date(imp['chain_date'])}, expiring {fmt_date(imp['expiration'])}"))
        sentences.append(f"Options price a move of about ±{num(imp['pct'])}% by {fmt_date(imp['expiration'])}, the first expiration after the report.")
    holding = (f"its next report on {fmt_date(date_)}" if date_ and conf == "confirmed" else
               f"its next report, expected around {fmt_date(date_)}" if date_ else
               f"its next report, expected between {fmt_date(ne.window_start)} and {fmt_date(ne.window_end)}" if ne and getattr(ne, "window_start", None) else
               "its next report")
    check = C.report_check(name, typical["pct"], ordinary, holding) if typical else None
    deeper = []
    if typical:
        deeper.append(_num("Typical move after a report", f"±{num(typical['pct'])}%", f"Average size of the next-day move over {typical['n']} reports to {fmt_date(typical['as_of'])}"))
    if ne and getattr(ne, "note", None) and date_:
        deeper.append(_num("Where the date comes from", CONFIRMATION_WORDS.get(conf or "estimated", "Estimated"), fmt_date(date_)))
    due = (f"on {fmt_date(date_)}, a date the company has confirmed" if date_ and conf == "confirmed" else
           f"around {fmt_date(date_)}, a date the company hasn't confirmed" if date_ else
           f"between {fmt_date(ne.window_start)} and {fmt_date(ne.window_end)}, judging by its past reports" if ne and getattr(ne, "window_start", None) else None)
    typ = f"has moved ±{num(typical['pct'])}% on a typical report day" if typical else None
    summary = (f"It reports next {due}" + (f", and {typ}." if typ else ".")) if due else f"It {typ}."
    fact = point = None
    if typical:
        k = C.report_multiple(typical["pct"], ordinary)
        fact = ({"concept": "report_move", "measure": "report_multiple", "lead": f"{name}'s report days swing {num(k)} times an ordinary day",
                 "short": f"{name}'s swing {num(k)} times", "tail": ""} if k else None) or \
               {"concept": "report_move", "measure": "typical", "lead": f"{name} has moved ±{num(typical['pct'])}% on a typical report day", "short": f"{name} has moved ±{num(typical['pct'])}%",
                "tail": f"over its last {typical['n']} reports"}
        point = f"Its typical ±{num(typical['pct'])}% move on a report day"
    st = _step(6, status="ok" if date_ or getattr(ne, "window_start", None) else "partial", numbers=numbers, sentences=sentences, idea="report_move", check=check,
               deeper=deeper, summary=summary, fact=fact, point=point,
               cell={"date": {"value": fmt_date(date_), "as_of": "Confirmed by the company" if conf == "confirmed" else "Not yet confirmed"}} if date_ else None)
    st["next_report"] = f"What its next report shows, due {due}." if due else None
    if not due:
        st["gap"] = f"{GAP_TOPIC[6]} (no date on file)"
    if fed_day:
        with_fed(st, fed_day)
    return st


# report_move_view's verdict (services/move_comparison.compare_moves) in step 6's words
OPTIONS_COMPARISON = {"more than usual": "more than", "less than usual": "less than", "about its usual": "about the same as"}
FED_SENTENCE = "The next Fed rate decision is on {day}, a day that can move the whole market."
FED_LABEL = "Next Fed decision"
FED_DECISION_HOUR = 14                          # the statement's time, New York (services/fomc_calendar)


def next_fed_day(now) -> date | None:
    """Pure: the next scheduled Fed decision as of `now` (a New York datetime): today's until its 2pm statement, else the next one."""
    from app.services.fomc_calendar import decision_days
    today = now.date()
    days = decision_days(today, today + timedelta(days=400))
    if days and days[0] == today and now.hour >= FED_DECISION_HOUR:
        days = days[1:]
    return days[0] if days else None


def with_fed(step: dict, fed_day: date | None) -> dict:
    """Pure (in place): step 6 with its Fed line and Go deeper row for fed_day, any earlier one replaced (routers/walkthrough.gate calls
    it with the day as served, so a stored payload never shows a decision that has passed)."""
    step["sentences"] = [x for x in step["sentences"] if not x.startswith("The next Fed rate decision")]
    step["deeper"] = [d for d in step["deeper"] if d["label"] != FED_LABEL]
    if fed_day and step["status"] != "absent":
        step["sentences"].append(FED_SENTENCE.format(day=day_words(fed_day)))
        step["deeper"].append(_num(FED_LABEL, day_words(fed_day), "Federal Reserve calendar"))
    return step


# ── step 7: risks ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def step_risks(name: str, risks: dict | None, merger: dict | None) -> dict:
    """Without the story step's verified sentences, a partial step pointing to the filing; build_walkthroughs fills `story`."""
    if not risks or not risks.get("ok"):
        why = _reason((risks or {}).get("reason"), RISK_REASONS, ("Its risk factors are not on file.", "its risk factors are not on file"))
        return _absent(7, name, why[0], why[1], "risk_factors")
    if predates(merger, risks.get("filed")):
        return _absent(7, name, f"It merged with {short_name(merger['name'])} on {fmt_date(merger['date'])}, and its last annual report predates the merger.",
                       "it merged after its last annual report", "risk_factors")
    source = {"label": f"Item 1A of its 10-K, filed {fmt_date(risks['filed'])}", "url": risks.get("url")}
    st = _step(7, status="partial", sentences=[f"{name} lists what could go wrong in Item 1A of its 10-K, filed {fmt_date(risks['filed'])}."],
               numbers=[], idea="risk_factors", source=source, summary=None)
    st["gap"] = f"{GAP_TOPIC[7]} (Ivy's plain summaries of its risks are not checked yet)"
    return st


def featured_risk(risk_sentences: list[dict], headings: dict[int, str], steps: list[dict]) -> tuple[dict, str] | None:
    """Pure: the risk step 7's check asks about, with the business result it maps to: the first shown risk that maps
    (walkthrough_checks.risk_target) to a business result this walkthrough shows, and whose sentence doesn't name that result's
    measure. None when the walkthrough doesn't show all of walkthrough_checks.RISK_OPTION_STEPS or no risk maps."""
    by_key = {s["key"]: s for s in steps if s["status"] != "absent" and s.get("point") and s["key"] in C.RISK_OPTION_STEPS}
    if len(by_key) < len(C.RISK_OPTION_STEPS):
        return None
    for r in risk_sentences:
        target = C.risk_target(headings.get(r["n"], ""), r["sentence"])
        if target and not C.RISK_GIVEAWAY[target].search(r["sentence"]):
            return r, target
    return None


def risk_check(name: str, risk_sentences: list[dict], headings: dict[int, str], steps: list[dict], noun: str = "revenue") -> dict | None:
    """Pure: step 7's check. The featured risk (featured_risk) asks which result it would hit most directly; the options are this
    walkthrough's business results (walkthrough_checks.RISK_OPTION_STEPS), all three shown. Otherwise no check."""
    f = featured_risk(risk_sentences, headings, steps)
    if f is None:
        return None
    r, target = f
    by_key = {s["key"]: s for s in steps if s["status"] != "absent" and s.get("point") and s["key"] in C.RISK_OPTION_STEPS}
    decoys = [by_key[k]["point"] for k in C.RISK_OPTION_STEPS if k != target]
    return C.risk_check(name, r["sentence"], by_key[target]["point"], decoys, noun)


def lead_lower(sentence: str, name: str) -> str:
    """Pure: a sentence continued mid-line ("among them that ..."): its first letter lowered unless it starts with a name (the company's
    own, "Apple's", or any word with a capital past its first letter, "JPMorgan")."""
    first = sentence.split()[0] if sentence.split() else ""
    bare = first.removesuffix("'s").removesuffix("’s")
    if bare == (name.split()[0] if name else None) or any(ch.isupper() for ch in bare[1:]):
        return sentence
    return sentence[:1].lower() + sentence[1:]


def with_risk_story(step: dict, name: str, risk_sentences: list[dict], headings: dict[int, str] | None = None, steps: list[dict] | None = None,
                    noun: str = "revenue") -> dict:
    """Pure: step 7 with the verified risk sentences ([{n, sentence}]) and its check."""
    if not risk_sentences:
        step["sentences"].append("Ivy's plain summaries of these risks are not checked yet, so read them in the filing.")
        return step
    step["sentences"] = [f"{name} names these among the risks in Item 1A of its 10-K, filed {step['source']['label'].rsplit('filed ', 1)[-1]}."]
    step["risks"] = risk_sentences
    step["status"] = "ok"
    step["gap"] = None
    step["headings"] = {r["n"]: (headings or {}).get(r["n"], "") for r in risk_sentences}      # the shown risks' Item 1A headings, for the check's mapping at serve time
    step["check"] = risk_check(name, risk_sentences, headings or {}, steps or [], noun)
    # the summary's line names the risk step 7 featured: the one its check asks about, else the first one shown (Sam, 2026-10-19)
    f = featured_risk(risk_sentences, headings or {}, steps or []) if step["check"] else None
    lead = f[0] if f else risk_sentences[0]
    step["summary"] = f"Its annual report names risks, among them that {lead_lower(lead['sentence'], name)}"
    return step


# ── summary, compare, fingerprints ─────────────────────────────────────────────────────────────────────────────────────────

SAME_QUARTER_DAYS = 45            # two period ends this close are the same fiscal quarter (a 52/53-week year shifts the end a few days)
QUARTER_WHAT = {2: "its {noun} growth", 3: "how much of each {unit} it keeps", 5: "what investors pay for each $1 of its profit"}
QUARTER_WHAT_REIT = {5: "its price against FFO per share"}
QUARTER_IDEA = {2: "growth", 3: "margins", 5: "pe"}


def one_quarter(steps: list[dict], ends: dict[int, date | None], latest: date | None, periods: dict | None, name: str,
                noun: str = "revenue", reit: bool = False) -> list[int]:
    """One quarter across the steps (Sam's review of MU, 2026-11-02: step 2 showed fiscal Q3 2026 beside step 3 through fiscal Q4).

    The walkthrough's quarter is the latest one the company has reported: `latest` (scripts/build_walkthroughs: the newest quarter
    filed before its latest report on file, never one that has merely ended). A step whose figure is for an earlier quarter keeps that
    figure, labelled with its own period as every figure is, and says in one plain line that the newer quarter's figure is not on file
    yet (Sam, 2026-11-10: JPM's steps 2 and 5 had gone blank). Changes `steps` in place; returns the steps it marked."""
    if latest is None:
        return []
    marked = []
    for n, end in ends.items():
        if end is None or (latest - end).days <= SAME_QUARTER_DAYS or steps[n - 1]["status"] == "absent":
            continue
        what = (QUARTER_WHAT_REIT.get(n) if reit else None) or QUARTER_WHAT[n].format(noun=noun, unit=each_unit(noun))
        st = steps[n - 1]
        st["sentences"] = list(st["sentences"]) + [behind_line(what, quarter(periods, latest), quarter(periods, end))]
        st["status"] = "partial"
        st["behind"] = {"end": str(end), "latest": str(latest)}
        st["gap"] = f"{gap_topic(n, noun)} (not on file for {quarter(periods, latest)} yet)"
        marked.append(n)
    return marked


def reported_quarter(ends: list[date | None], reported_on: date | None) -> date | None:
    """Pure: the walkthrough's quarter: the newest of `ends` that ended before the company's latest report on file (a quarter that
    has ended but not been reported is never it); with no report on file, the newest of them."""
    known = [d for d in ends if d]
    if reported_on:
        known = [d for d in known if d < reported_on]
    return max(known, default=None)


def behind_line(what: str, latest_q: str, shown_q: str) -> str:
    """Pure: the one line a step adds when its figure is a quarter behind: "Its revenue growth for Q3 2026 isn't on file yet; the
    figures above are for Q2 2026, ended Jun 30, 2026." """
    return f"{cap(what)} for {latest_q} isn't on file yet; the figures above are for {shown_q}."


def summary(name: str, steps: list[dict]) -> dict:
    """What you now know (one takeaway per step shown), what's still uncertain (each step or part Ivy couldn't show and why, and the
    next report), the concepts met, and the closing line."""
    known = [{"n": s["n"], "line": s["summary"], "shown": True} for s in steps if s["status"] != "absent" and s.get("summary")]
    uncertain = [s["gap"] for s in steps if s.get("gap")]
    nxt = next((s.get("next_report") for s in steps if s["key"] == "upcoming" and s["status"] != "absent"), None)
    if nxt:
        uncertain.append(nxt)
    concepts = []
    for s in steps:
        idea = s.get("idea")
        if idea and s["status"] != "absent" and idea["concept"] not in [c["concept"] for c in concepts]:
            concepts.append({"concept": idea["concept"], "title": idea["title"]})
    return {"known": known, "uncertain": uncertain, "concepts": concepts, "closing": CLOSING_LINE}


def compare_row(name: str, symbol: str, steps: list[dict], *, reit: bool, noun: str = "revenue", ffo_growth: dict | None = None,
                dividend: dict | None = None) -> dict:
    """Compare's cells for one stock, each the figure its own walkthrough shows, by measure: {key: {measure: {value, as_of, end}}}
    ({} where it shows none). compare_table sets two stocks side by side on a measure both have."""
    by = {s["n"]: s for s in steps}
    shown = lambda n: (by[n].get("cell") or {}) if by[n]["status"] != "absent" else {}
    margins = shown(3)
    rows = {
        "sells": shown(1),
        "growth": shown(2),
        "keeps_now": margins.get("keeps_now") or {},
        "keeps_then": margins.get("keeps_then") or {},
        "stock_1y": shown(4),
        "valuation": shown(5),
        "ffo_growth": {"quarter": ffo_growth} if ffo_growth else {},
        "dividend_yield": {"close": dividend} if dividend else {},
        "next_report": shown(6),
    }
    return {"symbol": symbol, "name": name, "reit": reit, "noun": noun, "rows": rows}


COMPARE_LABELS = {"sells": "Biggest line", "growth": "Revenue growth", "ffo_growth": "FFO per share growth", "keeps_now": "Keeps per $1 now",
                  "keeps_then": "Keeps per $1 three years earlier", "stock_1y": "Stock over one year", "dividend_yield": "Dividend yield",
                  "next_report": "Next report"}
VALUATION_LABEL = {"pe": "Paid for each $1 of profit", "p_ffo": "Price to FFO"}
# the measures a row may use, most preferred first: both stocks are shown on the first one both have
COMPARE_MEASURES = {"sells": ("share",), "growth": ("ttm", "quarter"), "keeps_now": ("gross", "operating", "net"), "stock_1y": ("close",),
                    "valuation": ("pe", "p_ffo"), "ffo_growth": ("quarter",), "dividend_yield": ("close",), "next_report": ("date",)}
COMPARE_ORDER = ("sells", "growth", "keeps_now", "keeps_then", "stock_1y", "valuation", "next_report")
COMPARE_ORDER_REITS = ("sells", "growth", "ffo_growth", "keeps_now", "keeps_then", "stock_1y", "valuation", "dividend_yield", "next_report")
COMPARE_IDEA = ("Comparing", "Side by side works best on the same measures over the same periods. A company in the same industry shows what is normal for the business, and a company you know gives you a ruler for the rest.")
COMPARE_MISSING = "Not shown"


def shared_measure(a: dict, b: dict, prefs: tuple[str, ...]) -> str | None:
    """Pure: the first measure in prefs both sides have; with one side empty, the other's first; None when both show something but
    share no measure (the row is hidden), or neither shows anything."""
    both = [m for m in prefs if m in a and m in b]
    if both:
        return both[0]
    if a and b:
        return None
    return next((m for m in prefs if m in (a or b)), None)


def far_apart(x: dict | None, y: dict | None) -> bool:
    """Pure: two cells whose periods end more than COMPARE_PERIOD_DAYS apart."""
    if not x or not y or not x.get("end") or not y.get("end"):
        return False
    return abs((date.fromisoformat(x["end"][:10]) - date.fromisoformat(y["end"][:10])).days) > COMPARE_PERIOD_DAYS


def compare_table(a: dict, b: dict) -> list[dict]:
    """Pure: [{key, label, a, b}] for a pair: REIT rows for two trusts, the usual rows otherwise. Each row sets both stocks on one
    measure (COMPARE_MEASURES; the two margin rows share theirs, labelled), and is left out when neither stock shows it, when both
    show it on different measures, or when their periods end more than COMPARE_PERIOD_DAYS apart."""
    from app.services.margins import MEASURE_LABEL
    ra, rb = bool(a.get("reit")), bool(b.get("reit"))
    revenue = "revenue" in (a.get("noun"), b.get("noun"))
    order = COMPARE_ORDER_REITS if ra and rb else COMPARE_ORDER
    margin = shared_measure(a["rows"].get("keeps_now") or {}, b["rows"].get("keeps_now") or {}, COMPARE_MEASURES["keeps_now"])
    out = []
    for k in order:
        ca, cb = a["rows"].get(k) or {}, b["rows"].get(k) or {}
        m = margin if k in ("keeps_now", "keeps_then") else shared_measure(ca, cb, COMPARE_MEASURES[k])
        if m is None:
            continue
        x, y = ca.get(m), cb.get(m)
        if (x is None and y is None) or far_apart(x, y):
            continue
        if k == "valuation":
            label = VALUATION_LABEL[m]
        elif k in ("keeps_now", "keeps_then"):
            label = f"{COMPARE_LABELS[k]} ({MEASURE_LABEL[m]})"
        elif k == "growth" and revenue:
            label = "Revenue growth"
        else:
            label = COMPARE_LABELS[k]
        out.append({"key": k, "label": label, "a": x, "b": y})
    return out


AN_ENTITY = {"Banks": "bank", "REITs": "REIT", "Utilities": "utility", "Multi-Utilities": "multi-utility", "Manufacturers": "manufacturer", "Distributors": "distributor",
             "Airlines": "airline", "Brokers": "broker", "Restaurants": "restaurant company", "Semiconductors": "semiconductor company",
             "Pharmaceuticals": "pharmaceutical company"}
AN_SPECIAL = {"Trading Companies & Distributors": "trading company or distributor", "Distillers & Vintners": "distiller or vintner",
              "Independent Power Producers & Energy Traders": "independent power producer or energy trader", "Multi-Sector Holdings": "multi-sector holding company"}


def _lower(words: str) -> str:
    return " ".join(w if w.isupper() or w.endswith("REITs") or w.endswith("REIT") else w.lower() for w in words.replace("&", "and").split())


def another(industry: str | None, sector: str | None = None) -> str:
    """Compare's label for the rule-chosen company: "another semiconductor company", "another diversified bank", "another retail REIT",
    "another systems software company"; with only the sector to go on, "another information technology company"."""
    if not industry:
        return f"another {_lower(sector)} company" if sector else "another S&P 500 company"
    if industry in AN_SPECIAL:
        return f"another {AN_SPECIAL[industry]}"
    head, _, last = industry.rpartition(" ")
    if last in AN_ENTITY:
        tail = AN_ENTITY[last]
        return f"another {(_lower(head) + ' ') if head else ''}{tail}"
    return f"another {_lower(industry)} company"


def fingerprint(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:32]


def steps_shown(steps: list[dict]) -> int:
    return sum(1 for s in steps if s["status"] != "absent")
