"""The ticker Overview: two short labelled blocks from stored rows, each carrying its own receipt.

  profile     "What it is": the company's profile as Intrinio stores it, and its market value in plain words.
  happening   "What's been happening": the quote with its time, where it sits against the 52-week high and over
              three months, then the one nearest earnings fact (the reported state inside a report's reaction
              window, else the next report with the options-implied move against the typical one).

Each block is a pure function of plain inputs (fixture-tested) and returns {key, text, rule, as_of, inputs} or None
when its data is absent. Nothing here is typed by hand except the templates; every number in a block's text is one
of its inputs (tests/test_briefing.py checks this), and every lookback or threshold the wording depends on is a
named constant rendered into the block's rule. Absent data is omitted, never estimated.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.trading_calendar import is_trading_day, last_session_before, nth_trading_day_after

NY = ZoneInfo("America/New_York")

WINDOW_52W_DAYS = 366          # calendar days behind "52-week high"
WINDOW_3M_DAYS = 92            # calendar days behind "three months"
REACTION_WINDOW_SESSIONS = 5   # a report is "inside its reaction window" through this many sessions after it
DESCRIPTION_SENTENCES = 2      # how much of Intrinio's short description "What it is" quotes
TIMING_PHRASE = {"bmo": "before the open", "amc": "after the close"}
SOURCE_NAMES = {"yfinance": "Yahoo Finance", "finnhub": "Finnhub", "company": "the company", "edgar": "EDGAR"}   # reader-facing names; receipts keep the technical ones


# ── formatting ───────────────────────────────────────────────────────────────

def fmt_date(d: date | None) -> str | None:
    return d.strftime("%b %-d, %Y") if d else None


def fmt_quote_time(ts: int | None) -> str | None:
    """"Oct 5, 4:00 PM ET" from a Unix last-trade time, on the New York clock."""
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), NY).strftime("%b %-d, %-I:%M %p ET")


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


def _sentence(key: str, text: str, rule: str, as_of: date | str | None, inputs: list[dict]) -> dict:
    iso = as_of.isoformat() if isinstance(as_of, date) else as_of
    return {"key": key, "text": text, "rule": rule, "as_of": iso, "inputs": inputs}


def _input(name: str, value, as_of: date | str | None = None, source: str | None = None) -> dict:
    iso = as_of.isoformat() if isinstance(as_of, date) else as_of
    return {"name": name, "value": str(value), "as_of": iso, "source": source}


def evidence_phrase(note: str | None) -> str | None:
    """The evidence kind from a calendar note ("confirmed: press release via Finnhub news 2026-09-10: <headline>"), without the headline."""
    if not note:
        return None
    body = note.split(":", 1)[1].strip() if note.lower().startswith("confirmed:") else note.strip()
    return body.split(":", 1)[0].strip() or None
def confidence_phrase(confirmation: str | None, note: str | None, source: str | None) -> str | None:
    if confirmation == "confirmed":
        ev = evidence_phrase(note)
        return "confirmed by the company" + (f" ({ev})" if ev else "")
    if confirmation == "estimated":
        name = source_name(source)
        return "an estimate" + (f" ({name})" if name else "")
    if confirmation == "expected_unconfirmed":
        return "expected around then, not confirmed"
    return None
def settle_session(event_date: date, timing: str | None) -> date | None:
    """The session whose close settles the 1-day move: the report day before the open, the next session after the close."""
    if timing == "bmo":
        return event_date if is_trading_day(event_date) else nth_trading_day_after(event_date, 1)
    if timing == "amc":
        return nth_trading_day_after(event_date, 1)
    return None
def in_reaction_window(event_date: date, today: date) -> bool:
    return event_date <= today <= nth_trading_day_after(event_date, REACTION_WINDOW_SESSIONS)
def move_dates(event_date: date, timing: str | None) -> tuple[date | None, date | None]:
    """(base close date, 1-day close date): the seeder's windows. After the close: close(T) to close(T+1); before the open: close(T-1) to close(T)."""
    if timing == "amc":
        return event_date, nth_trading_day_after(event_date, 1)
    if timing == "bmo":
        return last_session_before(event_date), event_date
    return None, None

def market_value_words(market_cap: float | None) -> str | None:
    """"$1.2 trillion", "$23 billion", "$640 million": the market value in plain words, two significant figures."""
    if market_cap is None or market_cap <= 0:
        return None
    for unit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if market_cap >= unit:
            v = market_cap / unit
            return f"${v:.1f} {word}" if v < 10 else f"${v:.0f} {word}"
    return f"${market_cap:,.0f}"


ABBREVIATIONS = {"inc", "corp", "co", "ltd", "plc", "llc", "lp", "sa", "nv", "ag", "mr", "ms", "dr", "st", "no", "vs", "u.s", "e.g", "i.e"}


def first_sentences(text: str | None, n: int = DESCRIPTION_SENTENCES) -> str | None:
    """The first `n` sentences of a description, as written. A period after a company suffix (Inc., Corp., Ltd.) or
    another common abbreviation does not end a sentence."""
    import re
    if not text:
        return None
    body = text.strip()
    ends = []
    for m in re.finditer(r"[.!?](?=\s+[A-Z\"'(]|$)", body):
        before = body[:m.start()].rstrip()
        word = re.split(r"[\s(]", before)[-1].lower().rstrip(".") if before else ""
        if m.group() == "." and word in ABBREVIATIONS:
            continue
        ends.append(m.end())
        if len(ends) == n:
            break
    out = body[:ends[-1]].strip() if ends else body
    return out if out.endswith((".", "!", "?")) else out + "."


# ── block 1: what it is ──────────────────────────────────────────────────────

def profile_sentence(*, short_description: str | None = None, sector: str | None = None, industry: str | None = None,
                     profile_as_of: date | None = None, market_cap: float | None = None, market_cap_as_of: date | None = None) -> dict | None:
    """One or two sentences from the stored company profile and the stored market value; None without a profile."""
    desc = first_sentences(short_description)
    if not desc and not (sector or industry):
        return None
    inputs: list[dict] = []
    dates: list[date] = []
    text = desc or ""
    if desc:
        inputs.append(_input("description", desc, profile_as_of, "Intrinio company profile (company_profiles.short_description)"))
    bits = []
    if industry:
        bits.append(f"{industry} company" if not sector else f"{industry} company in the {sector} sector")
        inputs.append(_input("industry", industry, profile_as_of, "Intrinio company profile (industry_group)"))
        if sector:
            inputs.append(_input("sector", sector, profile_as_of, "Intrinio company profile (sector)"))
    elif sector:
        bits.append(f"company in the {sector} sector")
        inputs.append(_input("sector", sector, profile_as_of, "Intrinio company profile (sector)"))
    mv = market_value_words(market_cap)
    if mv and market_cap_as_of:
        bits.append(f"worth about {mv} at market as of {fmt_date(market_cap_as_of)}")
        inputs.append(_input("market value", mv, market_cap_as_of, "tickers.market_cap (Finnhub profile)"))
        dates.append(market_cap_as_of)
    if bits:
        second = ("It is an " if bits[0][0].lower() in "aeiou" else "It is a ") + bits[0] + (", " + bits[1] if len(bits) > 1 else "") + "."
        text = f"{text} {second}".strip()
    if profile_as_of:
        dates.append(profile_as_of)
    rule = (f"The first {DESCRIPTION_SENTENCES} sentences of Intrinio's company description, its industry and sector, as stored by the nightly records "
            "step and dated by that fetch; the market value is the stored Finnhub market cap in round words, dated by its own refresh.")
    return _sentence("profile", text, rule, max(dates) if dates else None, inputs)


# ── block 2: what's been happening ──────────────────────────────────────────

def price_clause(symbol: str, *, quote_price: float | None, quote_ts: int | None, high_52w: float | None = None, high_52w_date: date | None = None,
                 anchor_close_3m: float | None = None, anchor_date_3m: date | None = None, last_close: float | None = None,
                 last_close_date: date | None = None) -> tuple[str, list[dict], list[date]] | None:
    """"MU last traded at $X (time), N% below its 52-week high of $H set <date>, up Y% over three months": the quote
    against the stored bars; the last close only in the receipt. None without a dated quote."""
    if quote_price is None or not quote_ts:
        return None
    t = fmt_quote_time(quote_ts)
    bits = [f"{symbol} last traded at {fmt_money(quote_price)} ({t})"]
    inputs = [_input("quote price", fmt_money(quote_price), t, "quote cache, dated by its last trade"), _input("quote time", t, t, "last trade")]
    dates = [datetime.fromtimestamp(int(quote_ts), NY).date()]
    if high_52w and high_52w_date:
        below = (high_52w - quote_price) / high_52w * 100
        if below < 0.05:
            bits.append("at a 52-week high")
        else:
            bits.append(f"{fmt_pct(below, signed=False)} below its 52-week high of {fmt_money(high_52w)} set {fmt_date(high_52w_date)}")
            inputs.append(_input("distance below 52-week high", fmt_pct(below, signed=False), high_52w_date, "quote against the stored daily bars"))
        inputs.append(_input("52-week high", fmt_money(high_52w), high_52w_date, "stored daily bars (price_bars_shadow), highest close"))
    if anchor_close_3m and anchor_date_3m:
        change = (quote_price / anchor_close_3m - 1) * 100
        bits.append(f"{'up' if change >= 0 else 'down'} {fmt_pct(abs(change), signed=False)} over three months")
        inputs += [_input("three-month change", fmt_pct(change), anchor_date_3m, "quote against the three-month anchor close"),
                   _input("three-month anchor close", fmt_money(anchor_close_3m), anchor_date_3m, f"first stored close on or after {WINDOW_3M_DAYS} calendar days back")]
    if last_close is not None and last_close_date:
        inputs.append(_input("last close", fmt_money(last_close), last_close_date, "stored daily bars (price_bars_shadow)"))
    return ", ".join(bits) + ".", inputs, dates


def reported_clause(*, today: date, event_date: date, timing: str | None = None, eps_actual: float | None = None, eps_estimate: float | None = None,
                    outcome: str | None = None, pct_change_1d: float | None = None, bars_through: date | None = None) -> tuple[str, list[dict], list[date]]:
    """"Reported <date> <timing>, EPS $a against a $e estimate, a beat, and the stock moved +x% the next session." pct_change_1d is the
    stored row's move or the one the builder computed from the stored bars with the seeder's own window; the settle wording is used
    only while the second bar is missing."""
    inputs = [_input("report date", fmt_date(event_date), event_date, "events"), _input("report timing", timing or "unknown", event_date, "events.report_timing")]
    bits = [f"Reported {fmt_date(event_date)}" + (f" {TIMING_PHRASE[timing]}" if timing in TIMING_PHRASE else "")]
    if eps_actual is not None and eps_estimate is not None:
        word = {"beat": "a beat", "miss": "a miss", "meet": "in line"}.get(outcome or "", None)
        bits.append(f"EPS {fmt_money(eps_actual)} against a {fmt_money(eps_estimate)} estimate" + (f", {word}" if word else ""))
        inputs += [_input("EPS actual", fmt_money(eps_actual), event_date, "events.eps_actual (Finnhub, else Yahoo Finance), the night of the report"),
                   _input("EPS estimate", fmt_money(eps_estimate), event_date, "events.eps_estimate"), _input("outcome", outcome or "unknown", event_date, "actual above estimate is a beat")]
    else:
        bits.append("EPS not yet reported to us")
    base_date, after_date = move_dates(event_date, timing)
    span = f"close {fmt_date(base_date)} to close {fmt_date(after_date)}" if base_date and after_date else None
    when = "that session" if timing == "bmo" else "the next session"
    if pct_change_1d is not None and span:
        bits.append(f"and the stock moved {fmt_pct(pct_change_1d)} {when} (1-day move, {span})")
        inputs += [_input("1-day move", fmt_pct(pct_change_1d), after_date, "stored bars through the seeder's window (close to close)"), _input("1-day move window", span, after_date, "trading calendar")]
    elif after_date is None:
        bits.append("and the 1-day move is recorded once the report timing is known")
    elif after_date == today:
        bits.append("and the 1-day move settles at today's close")
        inputs.append(_input("settlement session", fmt_date(after_date), after_date, "trading calendar"))
    elif after_date > today:
        bits.append(f"and the 1-day move settles at the close on {fmt_date(after_date)}")
        inputs.append(_input("settlement session", fmt_date(after_date), after_date, "trading calendar"))
    else:
        bits.append(f"and the 1-day move ({span}) is not yet stored")
        inputs.append(_input("newest stored bar", fmt_date(bars_through) if bars_through else "none", bars_through, "price_bars_shadow"))
    return ", ".join(bits) + ".", inputs, [event_date]


def upcoming_clause(*, today: date, next_date: date, confirmation: str | None = None, note: str | None = None, source: str | None = None,
                    timing: str | None = None, implied_pct: float | None = None, chain_date: date | None = None, expiration: date | None = None,
                    avg_abs_1d: float | None = None, sample_n: int = 0, sample_as_of: date | None = None) -> tuple[str, list[dict], list[date]]:
    """Reports <date> <timing>, <n> days away, <confidence>; options price about ±X% (chain dated ...) against a typical ±Y% over the last N reports."""
    days = (next_date - today).days
    bits = [f"Reports {fmt_date(next_date)}" + (f" {TIMING_PHRASE[timing]}" if timing in TIMING_PHRASE else ""), "today" if days == 0 else plural(days, "day away", "days away")]
    conf = confidence_phrase(confirmation, note, source)
    if conf:
        bits.append(conf)
    inputs = [_input("next earnings date", fmt_date(next_date), next_date, source), _input("days away", days, today),
              _input("report timing", timing or "unknown", next_date, "events.report_timing"), _input("confidence", confirmation or "none", next_date, note)]
    ev = evidence_phrase(note) if confirmation == "confirmed" else None
    if ev:
        inputs.append(_input("evidence", ev, next_date, "earnings calendar note"))
    dates = [next_date]
    text = ", ".join(bits)
    tail = []
    if implied_pct is not None and chain_date:
        pct = fmt_pct(implied_pct * 100, signed=False)
        tail.append(f"options price about ±{pct}" + (f" through {fmt_date(expiration)}" if expiration else "") + f" (chain dated {fmt_date(chain_date)})")
        inputs += [_input("implied move", pct, chain_date, "ATM straddle over spot, services/implied_move"), _input("chain date", fmt_date(chain_date), chain_date, "options chain last trade")]
        if expiration:
            inputs.append(_input("expiration", fmt_date(expiration), expiration, "chosen expiry"))
        dates.append(chain_date)
    if avg_abs_1d is not None and sample_n > 0:
        avg = fmt_pct(avg_abs_1d, signed=False)
        tail.append((f"against a typical ±{avg}" if tail else f"its typical move has been ±{avg}") + f" over {last_reports(sample_n)}")
        inputs += [_input("typical absolute 1-day move", avg, sample_as_of, "historical_reactions, mean absolute 1-day move of earnings rows"), _input("reports in the sample", sample_n, sample_as_of)]
        if sample_as_of:
            dates.append(sample_as_of)
    if tail:
        text += "; " + " ".join(tail)
    return text + ".", inputs, dates


def happening_sentence(symbol: str, *, price: dict | None = None, reported: dict | None = None, upcoming: dict | None = None) -> dict | None:
    """The block: the price clause, then the one nearest earnings fact (reported state wins when inside the window). None when both are absent."""
    parts: list[tuple[str, list[dict], list[date]]] = []
    pc = price_clause(symbol, **price) if price else None
    if pc:
        parts.append(pc)
    if reported:
        parts.append(reported_clause(**reported))
    elif upcoming and upcoming.get("next_date"):
        parts.append(upcoming_clause(**upcoming))
    if not parts:
        return None
    text = " ".join(p[0] for p in parts)
    inputs = [i for p in parts for i in p[1]]
    dates = [d for p in parts for d in p[2]]
    rule = (f"Price from the latest quote, dated by its last trade; the distance from the 52-week high (highest stored close over {WINDOW_52W_DAYS} calendar days) "
            f"and the change over {WINDOW_3M_DAYS} calendar days compare that quote with the stored Intrinio bars. Through {REACTION_WINDOW_SESSIONS} sessions after a "
            "report: EPS from the event row, fetched the night of the report, beat or miss against the estimate, and the 1-day move from the stored bars through the "
            "seeder's window (close of the report day to the next session's close after an after-close report, the prior close to the report day's close before the open). "
            "Otherwise the next report from the stored earnings calendar (a confirmed date needs company evidence; an estimate names its source), the at-the-money straddle "
            "over spot from the latest fresh options chain, and the mean absolute 1-day move across stored earnings reactions.")
    return _sentence("happening", text, rule, max(dates) if dates else None, inputs)


def paragraph(sentences: list[dict]) -> str:
    return " ".join(s["text"] for s in sentences)
