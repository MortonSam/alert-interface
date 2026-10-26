"""The ticker Overview: two short labelled blocks for someone who has never heard of the company.

  profile     "What it is": the company's own description (one or two complete sentences, capped), then one sentence
              built from stored fields: sector, industry and market value in plain words.
  happening   "What's been happening": sentence A, the stock (quote with its time, where it sits against the 52-week
              high, the three-month change); sentence B, the one thing a newcomer should know now, by priority:
              the reported state inside a report's reaction window, else a big non-earnings move in the last month,
              else the next report within NEXT_WITHIN_DAYS, else nothing.

Every block is a pure function of plain inputs (fixture-tested) and returns {key, text, rule, as_of, inputs} or None
when its data is absent. Nothing here is typed by hand except the templates: every number in a block's text is one of
its inputs (tests/test_briefing.py), every lookback or threshold is a named constant rendered into the rule, and no
plumbing word reaches the visible text. Absent data is omitted, never estimated.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from app.services.dates import fmt_days_in
from app.services.ffo import DERIVED_NOTE
from app.services.trading_calendar import is_trading_day, last_session_before, nth_trading_day_after

NY = ZoneInfo("America/New_York")

WINDOW_52W_DAYS = 366          # calendar days behind "52-week high"
WINDOW_3M_DAYS = 92            # calendar days behind "three months"
NEAR_HIGH_PCT = 2              # within this many percent of the 52-week high reads "near its 52-week high"
REACTION_WINDOW_SESSIONS = 5   # a report is "inside its reaction window" through this many sessions after it
BIG_MOVE_SESSIONS = 20         # "the past month": sessions searched for the biggest non-earnings daily move
BIG_MOVE_MULTIPLE = 4          # a move at least this many times the median absolute daily move of the past year is big
NEXT_SOON_DAYS = 7             # a report this close outranks a big move
NEXT_WITHIN_DAYS = 45          # the next report is worth a sentence only this close
DESCRIPTION_SENTENCES = 2      # at most this many sentences of the company's description
DESCRIPTION_CAP = 280          # characters; whole sentences are dropped to fit, never cut (a lone first sentence may exceed it)
SECOND_SENTENCE_IF_FIRST_UNDER = 120   # characters: the second sentence joins only after a short first one
LISTING_COMMAS = 3             # a sentence with this many commas is a list of segments, products or brands, not a description
LISTING_STARTS = ("the company operates through", "it operates through", "its ")   # "Its <x> segment offers ..." is a listing
# names that read badly when shortened from the stored one: BNY's stored name is cut off ("The Bank of New York Mellon Cor"),
# and Southern Company alone reads as a region. Keyed by symbol; the name a sentence uses, exactly.
DISPLAY_NAMES = {"BNY": "BNY", "SO": "Southern Company", "AIG": "AIG", "PEG": "PSEG", "DIS": "Disney", "HIG": "Hartford",
                 "VZ": "Verizon", "TMUS": "T-Mobile", "COIN": "Coinbase"}
TRAILING_WORDS = ("group", "companies")   # dropped from the end of a shortened name when a word remains: "Cigna Group" reads "Cigna"
NAME_SUFFIXES = ("incorporated", "inc", "corporation", "corp", "company", "co", "plc", "ltd", "limited", "holdings")   # stripped from the end of a company name
TIMING_PHRASE = {"bmo": "before the open", "amc": "after the close"}
SOURCE_NAMES = {"yfinance": "earnings calendar", "finnhub": "earnings calendar", "company": "the company", "edgar": "SEC filing"}   # reader-facing names; receipts keep the technical ones
ABBREVIATIONS = {"inc", "corp", "co", "ltd", "plc", "llc", "lp", "sa", "nv", "ag", "mr", "ms", "dr", "st", "no", "vs", "u.s", "e.g", "i.e"}
MARKET_VALUE_AGREEMENT = 0.25  # quote x shares shown only within this share of the dated market cap on file; past it the share count is
                               # stale (VMRK on 2026-10-15: a pre-merger 374.9M shares gave $23B against a $47B market cap), so no value
BOILERPLATE = ("was incorporated", "is incorporated", "was formerly known", "changed its name", "formerly known as")   # investor-relations sentences dropped


# ── formatting ───────────────────────────────────────────────────────────────

def fmt_date(d: date | None) -> str | None:
    return d.strftime("%b %-d, %Y") if d else None


def fmt_quote_time(ts: int | None) -> str | None:
    """"Oct 5, 2026, 4:00 PM ET" from a Unix last-trade time, on the New York clock: the site's one time format (frontend DESIGN.md)."""
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), NY).strftime("%b %-d, %Y, %-I:%M %p ET")


def fmt_money(x: float | None) -> str | None:
    return None if x is None else f"${x:,.2f}"


def fmt_pct(x: float | None, signed: bool = True, places: int = 1) -> str | None:
    if x is None:
        return None
    return f"{x:+.{places}f}%" if signed else f"{x:.{places}f}%"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def last_reports(n: int) -> str:
    return "the last report" if n == 1 else f"the last {n} reports"


def source_name(source: str | None) -> str | None:
    return SOURCE_NAMES.get((source or "").lower(), source) if source else None


def market_value_words(market_cap: float | None) -> str | None:
    """"$1.2 trillion", "$19 billion", "$850 million": one decimal at most, none from ten up."""
    if market_cap is None or market_cap <= 0:
        return None
    for unit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if market_cap >= unit:
            v = market_cap / unit
            return f"${v:.1f} {word}" if v < 10 else f"${v:.0f} {word}"
    return f"${market_cap:,.0f}"


def _sentence(key: str, text: str, rule: str, as_of: date | str | None, inputs: list[dict]) -> dict:
    iso = as_of.isoformat() if isinstance(as_of, date) else as_of
    return {"key": key, "text": text, "rule": rule, "as_of": iso, "inputs": inputs}


def _input(name: str, value, as_of: date | str | None = None, source: str | None = None) -> dict:
    iso = as_of.isoformat() if isinstance(as_of, date) else as_of
    return {"name": name, "value": str(value), "as_of": iso, "source": source}


# ── block 1: what it is ──────────────────────────────────────────────────────

def split_sentences(text: str) -> list[str]:
    """Complete sentences, as written; a period after a company suffix or another abbreviation does not end one."""
    body = (text or "").strip()
    out, start = [], 0
    for m in re.finditer(r"[.!?](?=\s+[A-Z\"'(]|$)", body):
        word = re.split(r"[\s(]", body[start:m.start()].rstrip())[-1].lower().rstrip(".")
        if m.group() == "." and word in ABBREVIATIONS:
            continue
        out.append(body[start:m.end()].strip())
        start = m.end()
    if body[start:].strip():
        out.append(body[start:].strip() + ("" if body.rstrip().endswith((".", "!", "?")) else "."))
    return out


def is_listing(sentence: str) -> bool:
    """A sentence that lists segments, products or brands: starts like one, or carries LISTING_COMMAS commas or more."""
    low = sentence.strip().lower()
    return low.startswith(LISTING_STARTS) or sentence.count(",") >= LISTING_COMMAS


def description_text(short_description: str | None) -> str | None:
    """The first sentence of the description (boilerplate dropped); the second joins only when the first is under
    SECOND_SENTENCE_IF_FIRST_UNDER characters, the second is not a listing, and the pair fits DESCRIPTION_CAP."""
    if not short_description:
        return None
    sentences = [x for x in split_sentences(short_description) if not any(b in x.lower() for b in BOILERPLATE)]
    if not sentences:
        return None
    out = [sentences[0]]
    if len(sentences) > 1 and len(sentences[0]) < SECOND_SENTENCE_IF_FIRST_UNDER and not is_listing(sentences[1]) \
            and len(sentences[0]) + 1 + len(sentences[1]) <= DESCRIPTION_CAP:
        out.append(sentences[1])
    return " ".join(out)


def short_name(name: str | None, symbol: str | None = None) -> str | None:
    """"Micron Technology" from "Micron Technology, Inc."; "Constellation Brands" from "Constellation Brands, Inc."; a leading
    "The" and a trailing "Group" or "Companies" are dropped so the name reads mid-sentence: "AES" from "The AES Corporation",
    "Home Depot" from "The Home Depot, Inc.", "Cigna" from "The Cigna Group". DISPLAY_NAMES wins for its symbols."""
    if symbol and symbol.upper() in DISPLAY_NAMES:
        return DISPLAY_NAMES[symbol.upper()]
    if not name:
        return None
    import re as _re
    name = _re.sub(r"\s*\((?:The|HC)\)\s*$", "", name)      # "Goldman Sachs Group, Inc. (The)", "Kimco Realty Corporation (HC)"
    words = name.replace(",", " ").split()
    while len(words) > 1 and words[-1].lower().rstrip(".") in NAME_SUFFIXES:
        words.pop()
    if len(words) > 1 and words[0].lower() == "the":
        words.pop(0)
    while len(words) > 1 and words[-1].lower() in TRAILING_WORDS:
        words.pop()
    while len(words) > 1 and words[-1] in ("&", "and"):       # "JPMorgan Chase & Co." loses "Co." above and must not keep the "&"
        words.pop()
    return " ".join(words)


def merger_text(name: str | None, symbol: str | None, merged_name: str | None, merged_on: date | None) -> str | None:
    """Pure: the description of a company that took in another after its profile was written (2026-10-15, VMRK): the merger from
    its record, and that the profile on file predates it. None without both names and the date."""
    me, other = short_name(name, symbol), short_name(merged_name)
    if not (me and other and merged_on):
        return None
    return (f"{me} combined with {other} in a merger completed {fmt_date(merged_on)}. "
            f"Its company description on file predates the merger, so it is not shown.")


def market_value_agrees(quote_price: float | None, shares_outstanding: float | None, market_cap: float | None) -> bool:
    """Pure: quote x shares is within MARKET_VALUE_AGREEMENT of the dated market cap on file (True when there is no market cap to
    compare, so a ticker without one keeps its value)."""
    if not (quote_price and shares_outstanding):
        return False
    if not market_cap:
        return True
    return abs(quote_price * shares_outstanding / market_cap - 1) <= MARKET_VALUE_AGREEMENT


def profile_sentence(*, name: str | None = None, symbol: str | None = None, short_description: str | None = None, profile_as_of: date | None = None, profile_source: str | None = "Intrinio",
                     gics_sector: str | None = None, gics_sub_industry: str | None = None, gics_as_of: date | None = None, index_member: bool = False,
                     quote_price: float | None = None, quote_ts: int | None = None, shares_outstanding: float | None = None, shares_as_of: date | None = None,
                     profile_filed: date | None = None, merged_name: str | None = None, merged_on: date | None = None,
                     market_cap: float | None = None) -> dict | None:
    """The description, then "It's part of the S&P 500's <GICS sector> sector (<sub-industry>), worth about <quote x shares>." None without a profile.
    A merger into this company after the profile's latest filing replaces the description with the merger (merger_text); a market
    value that disagrees with the dated market cap on file is left out (market_value_agrees)."""
    desc = description_text(short_description)
    if not desc:
        return None
    merged = merged_on is not None and (profile_filed is None or merged_on > profile_filed)
    if merged:
        desc = merger_text(name, symbol, merged_name, merged_on) or desc
    inputs = [_input("description", desc, merged_on if merged else profile_as_of,
                     "the merger on file (ticker exits), the profile's own description left out because it predates it" if merged else "company profile, short description")]
    dates: list[date] = [d for d in (profile_as_of,) if d]
    if name:
        inputs.append(_input("company name", short_name(name, symbol), profile_as_of, f"company name on file, read as {name!r} with its corporate suffix dropped"))
    bits = []
    if gics_sector:
        bits.append((f"part of the S&P 500's {gics_sector} sector" if index_member else f"in the {gics_sector} sector") + (f" ({gics_sub_industry})" if gics_sub_industry else ""))
        inputs.append(_input("GICS sector", gics_sector, gics_as_of, "S&P 500 constituent list, the same source Discover shows"))
        if gics_sub_industry:
            inputs.append(_input("GICS sub-industry", gics_sub_industry, gics_as_of, "S&P 500 constituent list"))
        if index_member:
            inputs.append(_input("index membership", "S&P 500", gics_as_of, "the nightly S&P 500 constituent list"))
        if gics_as_of:
            dates.append(gics_as_of)
    from app.services.personal_use import shown
    # the shares outstanding and the market cap on file are Finnhub's (personal use only): no market value while that data is held
    mv = market_value_words(quote_price * shares_outstanding) if shown() and market_value_agrees(quote_price, shares_outstanding, market_cap) else None
    if mv and quote_ts and shares_as_of:
        bits.append(f"worth about {mv}")
        t = fmt_quote_time(quote_ts)
        inputs += [_input("market cap", mv, t, "latest quote times shares outstanding"), _input("quote", fmt_money(quote_price), t, "latest quote, dated by its last trade"),
                   _input("shares outstanding", f"{shares_outstanding / 1e6:,.1f} million", shares_as_of, "company profile")]
        dates += [datetime.fromtimestamp(int(quote_ts), NY).date(), shares_as_of]
    text = desc + (f" It's {', '.join(bits)}." if bits else "")
    rule = (f"The first sentence of the company's description as recorded by the nightly records step and dated by that fetch (a second sentence joins only after a first under "
            f"{SECOND_SENTENCE_IF_FIRST_UNDER} characters and when it is not a list of segments, products or brands; incorporation and renaming boilerplate removed; "
            f"{DESCRIPTION_CAP} characters at most, whole sentences only). Sector and sub-industry are GICS from the S&P 500 constituent list, never the profile vendor's "
            "categories; membership from the nightly list. The market value is the latest quote times the shares outstanding from the company profile, in round words, "
            "one decimal at most, each dated, and shown only within "
            f"{MARKET_VALUE_AGREEMENT:.0%} of the dated market cap on file. A merger into the company completed after its profile's latest filing replaces "
            "the description with the merger and the date it completed.")
    return _sentence("profile", text, rule, max(dates) if dates else None, inputs)


# ── block 2, sentence A: the stock ──────────────────────────────────────────

def stock_sentence(symbol: str, *, quote_price: float | None, quote_ts: int | None, high_52w: float | None = None, high_52w_date: date | None = None,
                   anchor_close_3m: float | None = None, anchor_date_3m: date | None = None, last_close: float | None = None,
                   last_close_date: date | None = None) -> tuple[str, list[dict], list[date]] | None:
    """"<SYM> is at $X (time), N% below its 52-week high of $H (date), up Y% over three months." Near the high within NEAR_HIGH_PCT
    reads "near its 52-week high". The last close is a receipt only. None without a dated quote."""
    if quote_price is None or not quote_ts:
        return None
    t = fmt_quote_time(quote_ts)
    bits = [f"{symbol} is at {fmt_money(quote_price)} ({t})"]
    inputs = [_input("quote", fmt_money(quote_price), t, "latest quote, dated by its last trade"), _input("quote time", t, t, "last trade")]
    dates = [datetime.fromtimestamp(int(quote_ts), NY).date()]
    if high_52w and high_52w_date:
        below = (high_52w - quote_price) / high_52w * 100
        if below < NEAR_HIGH_PCT:
            bits.append(f"near its 52-week high of {fmt_money(high_52w)} ({fmt_date(high_52w_date)})")
        else:
            bits.append(f"{fmt_pct(below, signed=False)} below its 52-week high of {fmt_money(high_52w)} ({fmt_date(high_52w_date)})")
            inputs.append(_input("distance below 52-week high", fmt_pct(below, signed=False), high_52w_date, "quote against the highest close"))
        inputs.append(_input("52-week high", fmt_money(high_52w), high_52w_date, f"daily closes, highest close over {WINDOW_52W_DAYS} days"))
    if anchor_close_3m and anchor_date_3m:
        change = (quote_price / anchor_close_3m - 1) * 100
        bits.append(f"{'up' if change >= 0 else 'down'} {fmt_pct(abs(change), signed=False)} over three months")
        inputs += [_input("three-month change", fmt_pct(change), anchor_date_3m, "quote against the three-month anchor close"),
                   _input("three-month anchor close", fmt_money(anchor_close_3m), anchor_date_3m, f"first close on or after {WINDOW_3M_DAYS} days back")]
    if last_close is not None and last_close_date:
        inputs.append(_input("last close", fmt_money(last_close), last_close_date, "daily closes"))
    return ", ".join(bits) + ".", inputs, dates


# ── block 2, sentence B: one thing to know now ──────────────────────────────

_VENDOR_NOTES = ((re.compile(r"Finnhub and Yahoo Finance agree", re.I), "two calendars agree"), (re.compile(r"press release via Finnhub news", re.I), "press release"),
                 (re.compile(r"estimated \((?:Finnhub|Yahoo Finance)\)", re.I), "estimated"), (re.compile(r"\b(?:Finnhub|Yahoo Finance) says\b", re.I), "another calendar says"),
                 (re.compile(r"not confirmed by Finnhub, Yahoo Finance or EDGAR", re.I), "not confirmed by any calendar or filing"))


def reader_note(note: str | None) -> str | None:
    """Pure: a calendar note as a visitor reads it: what kind of evidence, never which vendor supplied it."""
    if not note:
        return None
    for pat, plain in _VENDOR_NOTES:
        note = pat.sub(plain, note)
    return fmt_days_in(note)       # a note the nightly wrote before 2026-10-19 carries ISO days ("the last report was 2026-07-22")


def evidence_phrase(note: str | None) -> str | None:
    note = reader_note(note)
    if not note:
        return None
    body = note.split(":", 1)[1].strip() if note.lower().startswith("confirmed:") else note.strip()
    return body.split(":", 1)[0].strip() or None


def confidence_phrase(confirmation: str | None) -> str | None:
    return {"confirmed": "confirmed by the company", "estimated": "estimated", "expected_unconfirmed": "expected, not confirmed"}.get(confirmation or "")


def settle_session(event_date: date, timing: str | None) -> date | None:
    if timing == "bmo":
        return event_date if is_trading_day(event_date) else nth_trading_day_after(event_date, 1)
    if timing == "amc":
        return nth_trading_day_after(event_date, 1)
    return None


def move_dates(event_date: date, timing: str | None) -> tuple[date | None, date | None]:
    """(base close date, 1-day close date): the seeder's windows. After the close: close(T) to close(T+1); before the open: close(T-1) to close(T)."""
    if timing == "amc":
        return event_date, nth_trading_day_after(event_date, 1)
    if timing == "bmo":
        return last_session_before(event_date), event_date
    return None, None


def in_reaction_window(event_date: date, today: date) -> bool:
    return event_date <= today <= nth_trading_day_after(event_date, REACTION_WINDOW_SESSIONS)


def year_ago_clause(y: dict) -> str:
    """Pure: "EPS $2.22, up 111.4% from $1.05 a year ago", or "EPS $2.39, with no figure from the same quarter a year earlier on
    file" (a clause, so it sits inside the Overview's sentence)."""
    if y.get("sec_eps") is None:
        return y["eps_line"]                          # a held FFO quarter says so
    if y.get("year_ago_eps") is None:
        return f"{y.get('measure') or 'EPS'} {fmt_money(y['sec_eps'])}, with no figure from the same quarter a year earlier on file"
    return y["eps_line"]


def year_ago_with(y: dict) -> str | None:
    """Pure: W6's clause after the report date, "with EPS of $2.46, up 127.8% from $1.08 a year ago", or "with EPS of $2.39, with no
    figure from the same quarter a year earlier on file"; None for a held FFO quarter (its line is a sentence of its own)."""
    if y.get("sec_eps") is None:
        return None
    m = y.get("measure") or "EPS"
    clause = year_ago_clause(y)
    return f"with {m} of {clause[len(m) + 1:]}" if clause.startswith(f"{m} ") else clause


def reported_clause(*, today: date, event_date: date, timing: str | None = None, eps_actual: float | None = None, eps_estimate: float | None = None,
                    outcome: str | None = None, pct_change_1d: float | None = None, bars_through: date | None = None,
                    year_ago: dict | None = None) -> tuple[str, list[dict], list[date]]:
    """"Reported <date> <timing>: EPS $a against a $e estimate, a beat; the stock moved +x% the next session." The EPS clause is
    omitted without an actual; the move clause reads "the move settles at today's close" while the second bar is missing.
    `year_ago` (services/licensed_estimates.year_ago_fields, given when LICENSED_ESTIMATES is off) replaces the estimate clause
    with the quarter's EPS from SEC filings against the same quarter a year earlier, in W6's two sentences (Block 2 wording):
    "Reported Aug 26, 2026 after the close, with EPS of $2.46, up 127.8% from $1.08 a year ago. The stock moved +8.7% the next session."
    """
    inputs = [_input("report date", fmt_date(event_date), event_date, "earnings calendar"), _input("report timing", timing or "unknown", event_date, "earnings calendar, report timing")]
    head = f"Reported {fmt_date(event_date)}" + (f" {TIMING_PHRASE[timing]}" if timing in TIMING_PHRASE else "")
    clauses: list[str] = []
    first = head
    if year_ago is not None:
        ffo = year_ago.get("measure") == "FFO per share"
        if year_ago.get("sec_eps") is not None:
            first = f"{head}, {year_ago_with(year_ago)}"
            if ffo:
                inputs.append(_input("FFO per share", fmt_money(year_ago["sec_eps"]), year_ago["sec_eps_period_end"], "Nareit FFO per diluted share for the quarter, from the earnings release, checked against the company's SEC filings"
                                     + (DERIVED_NOTE if DERIVED_NOTE in (year_ago.get("eps_line") or "") else "")))      # W8: AMT and PLD
            else:
                inputs.append(_input("EPS (SEC filings)", fmt_money(year_ago["sec_eps"]), year_ago["sec_eps_period_end"], "GAAP diluted EPS for the quarter, from SEC filings"))
            if year_ago.get("year_ago_eps") is not None:
                inputs.append(_input("FFO per share a year earlier" if ffo else "EPS a year earlier", fmt_money(year_ago["year_ago_eps"]), year_ago["year_ago_period_end"],
                                     "the same quarter a year earlier, from its earnings release" if ffo else "the same quarter a year earlier, from SEC filings"))
        elif year_ago.get("eps_line"):
            first = f"{head}. {year_ago['eps_line'].rstrip('.')}"      # a held FFO quarter: the sentence says it is held
    elif eps_actual is not None and eps_estimate is not None:
        word = {"beat": "a beat", "miss": "a miss", "meet": "a match"}.get(outcome or "", None)
        clauses.append(f"EPS {fmt_money(eps_actual)} against a {fmt_money(eps_estimate)} estimate" + (f", {word}" if word else ""))
        inputs += [_input("EPS actual", fmt_money(eps_actual), event_date, "reported EPS, the night of the report"),
                   _input("EPS estimate", fmt_money(eps_estimate), event_date, "analyst consensus EPS estimate"), _input("outcome", outcome or "unknown", event_date, "actual above estimate is a beat")]
    base_date, after_date = move_dates(event_date, timing)
    when = "that session" if timing == "bmo" else "the next session"
    if pct_change_1d is not None and after_date:
        clauses.append(f"the stock moved {fmt_pct(pct_change_1d)} {when}")
        inputs += [_input("1-day move", fmt_pct(pct_change_1d), after_date, "daily closes (close to close)"),
                   _input("1-day move window", f"close {fmt_date(base_date)} to close {fmt_date(after_date)}", after_date, "trading calendar")]
    elif after_date is None:
        clauses.append("the move is recorded once the report timing is known")
    elif after_date == today:
        clauses.append("the move settles at today's close")
        inputs.append(_input("settlement session", fmt_date(after_date), after_date, "trading calendar"))
    elif after_date > today:
        clauses.append(f"the move settles at the close on {fmt_date(after_date)}")
        inputs.append(_input("settlement session", fmt_date(after_date), after_date, "trading calendar"))
    else:
        clauses.append(f"the move (close {fmt_date(base_date)} to close {fmt_date(after_date)}) is not yet on file")
        inputs.append(_input("newest daily bar", fmt_date(bars_through) if bars_through else "none", bars_through, "daily closes"))
    if year_ago is not None:                          # W6: the report and its EPS in one sentence, the move in the next
        move = clauses[-1]
        return f"{first}. {move[0].upper()}{move[1:]}.", inputs, [event_date]
    return f"{head}: " + "; ".join(clauses) + ".", inputs, [event_date]


def find_big_move(daily: list[tuple[date, float]], exclude: set[date], today: date) -> dict | None:
    """Pure: among the last BIG_MOVE_SESSIONS sessions, the largest absolute daily move not on an excluded date, if it is at least
    BIG_MOVE_MULTIPLE times the median absolute daily move of the past year. daily is [(session, pct close-to-close)] ascending."""
    year = [abs(p) for d, p in daily if d > today - timedelta(days=WINDOW_52W_DAYS)]
    if len(year) < BIG_MOVE_SESSIONS * 2:
        return None
    typical = median(year)
    if typical <= 0:
        return None
    recent = [(d, p) for d, p in daily[-BIG_MOVE_SESSIONS:] if d not in exclude]
    if not recent:
        return None
    d, p = max(recent, key=lambda x: abs(x[1]))
    if abs(p) < BIG_MOVE_MULTIPLE * typical:
        return None
    return {"move_date": d, "move_pct": p, "typical_abs": typical, "multiple": abs(p) / typical}


def big_move_clause(*, move_date: date, move_pct: float, typical_abs: float, multiple: float) -> tuple[str, list[dict], list[date]]:
    """"Its biggest move in the past month was +Z% on <date>, about N times a typical day for this stock." No cause is stated."""
    n = f"{multiple:.0f}"
    text = f"Its biggest move in the past month was {fmt_pct(move_pct)} on {fmt_date(move_date)}, about {n} times a typical day for this stock."
    inputs = [_input("biggest daily move", fmt_pct(move_pct), move_date, f"daily closes, close to close, largest absolute move of the last {BIG_MOVE_SESSIONS} sessions off earnings dates"),
              _input("typical daily move", fmt_pct(typical_abs, signed=False), move_date, f"median absolute daily move over {WINDOW_52W_DAYS} days"),
              _input("multiple of a typical day", n, move_date, f"at least {BIG_MOVE_MULTIPLE} to be shown")]
    return text, inputs, [move_date]


def report_move_inputs(view: dict) -> list[dict]:
    """The report move's receipts (services/report_move.report_move_view) as inputs, the same in the Overview and the strip: the
    move, its method, the two expirations it read with their implied volatilities, the chain date, and the typical move it is
    compared with."""
    rm = view.get("move")
    if rm is None or rm.after is None:
        return []
    cd = view.get("chain_date") or date.fromisoformat(rm.after.chain_date)
    out = []
    if view.get("rep") is not None:
        out.append(_input("report move", f"{view['rep']:.1f}%", cd, "0.80 x the report's one-day standard deviation, from the options around the report"))
        out.append(_input("report move method", "the expirations before and after the report" if rm.method == "pair" else "the first two expirations after the report", cd,
                          "services/report_move"))
    legs = [rm.before, rm.after] if rm.method == "pair" else [rm.after, rm.later]
    for leg in legs:
        if leg is not None and leg.atm_iv is not None:
            out.append(_input(f"implied volatility to {fmt_date(date.fromisoformat(leg.expiration))}", f"{leg.atm_iv * 100:.1f}%", cd, "at-the-money, from the options prices"))
    out.append(_input("chain date", fmt_date(cd), cd, "options chain last trade"))
    if view.get("move_comparison") and view.get("typical_move_pct") is not None:
        out += [_input("typical move after a report", f"{view['typical_move_pct']:.1f}%", None, f"past earnings reactions, mean absolute 1-day move over {last_reports(view['typical_n'])}"),
                _input("reports in the sample", view["typical_n"], None)]
    return out


def upcoming_clause(*, today: date, next_date: date, confirmation: str | None = None, note: str | None = None, source: str | None = None,
                    timing: str | None = None, report_view: dict | None = None) -> tuple[str, list[dict], list[date]]:
    """"Reports <date> <timing>, <N> days away (confirmed by the company)." then, when the options give one, the report move's own
    sentence (services/report_move.report_move_view), word for word the one the verdict, Discover and the strip state; when the
    options do not separate a report move, that sentence."""
    days = (next_date - today).days
    if confirmation == "expected_window":
        from app.services.next_earnings import expected_window_line
        return (expected_window_line(next_date) + ".", [_input("expected report day", fmt_date(next_date), today,
                "the window from its past report dates in SEC filings (services/report_windows)")], [])
    conf = confidence_phrase(confirmation)
    text = f"Reports {fmt_date(next_date)}" + (f" {TIMING_PHRASE[timing]}" if timing in TIMING_PHRASE else "") + ", " + ("today" if days == 0 else plural(days, "day away", "days away"))
    text += f" ({conf})" if conf else ""
    inputs = [_input("next earnings date", fmt_date(next_date), next_date, source_name(source) or source), _input("days away", days, today),
              _input("report timing", timing or "unknown", next_date, "earnings calendar, report timing"), _input("confidence", confirmation or "none", next_date, reader_note(note))]
    ev = evidence_phrase(note) if confirmation == "confirmed" else None
    if ev:
        inputs.append(_input("evidence", ev, next_date, "earnings calendar note"))
    dates = [next_date]
    text += "."
    v = report_view or {}
    from app.services.report_move import STATED
    if v.get("state") in STATED and v.get("comparison"):
        text += " " + v["comparison"]
        inputs += report_move_inputs(v)
        if v.get("chain_date"):
            dates.append(v["chain_date"])
    return text, inputs, dates


def happening_sentence(symbol: str, *, stock: dict | None = None, reported: dict | None = None, big_move: dict | None = None, upcoming: dict | None = None) -> dict | None:
    """Sentence A, then the first sentence B that applies: reported state, big move, next report. None when nothing applies."""
    parts: list[tuple[str, list[dict], list[date]]] = []
    a = stock_sentence(symbol, **stock) if stock else None
    if a:
        parts.append(a)
    days_to_report = (upcoming["next_date"] - upcoming["today"]).days if upcoming and upcoming.get("next_date") else None
    if reported:
        parts.append(reported_clause(**reported))
    elif days_to_report is not None and 0 <= days_to_report <= NEXT_SOON_DAYS:
        parts.append(upcoming_clause(**upcoming))
    elif big_move:
        parts.append(big_move_clause(**big_move))
    elif days_to_report is not None and 0 <= days_to_report <= NEXT_WITHIN_DAYS:
        parts.append(upcoming_clause(**upcoming))
    if not parts:
        return None
    text = " ".join(p[0] for p in parts)
    inputs = [i for p in parts for i in p[1]]
    today = (reported or upcoming or {}).get("today") or date.today()
    dates = [d for p in parts for d in p[2] if d <= today]          # an as-of is when we knew, never a report day still ahead
    rule = (f"The stock: the latest quote dated by its last trade, against its 52-week high (the highest close over {WINDOW_52W_DAYS} days; within {NEAR_HIGH_PCT}% reads near) and the "
            f"first close {WINDOW_3M_DAYS} days back. Then one of, in order: through {REACTION_WINDOW_SESSIONS} sessions after a report, {_reported_rule()} "
            f"and the 1-day move from the daily bars through the seeder's window; else a report within {NEXT_SOON_DAYS} days; "
            f"else the largest daily move of the last {BIG_MOVE_SESSIONS} sessions off earnings dates when it is at least {BIG_MOVE_MULTIPLE} times the median absolute daily "
            f"move of the past year, with no cause stated; else the next report within {NEXT_WITHIN_DAYS} days. A report comes from the earnings calendar, with the report move "
            "(the part of the options' expected move that belongs to the report alone) against the mean absolute 1-day move after past reports, the sentence Discover states.")
    return _sentence("happening", text, rule, max(dates) if dates else None, inputs)


def _reported_rule() -> str:
    """The rule's words for the reported clause, as the clause is built: with LICENSED_ESTIMATES off (W6) the reported EPS from SEC
    filings against the same quarter a year earlier; no estimate or beat is named then (Block 2: the Overview's method still said
    "actual above estimate is a beat" on every ticker page after stage 1)."""
    from app.services.licensed_estimates import licensed
    if licensed():
        return "the EPS on the event row against the estimate (actual above estimate is a beat)"
    return "the reported EPS from SEC filings against the same quarter a year earlier"


def paragraph(sentences: list[dict]) -> str:
    return " ".join(s["text"] for s in sentences)
