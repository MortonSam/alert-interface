"""The ticker briefing: templated sentences from stored rows, each carrying its own receipt.

Every sentence is a pure function of plain inputs (so each is fixture-tested) and returns
{key, text, rule, as_of, inputs} or None when its data is absent. Nothing here is typed by hand except the
templates; every number in a sentence's text is one of its inputs (tests/test_briefing.py checks this), and
every lookback or threshold the wording depends on is a named constant rendered into the sentence's rule.
Absent data is omitted, never estimated.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from app.services.trading_calendar import is_trading_day, last_session_before, nth_trading_day_after
from app.thresholds import rv_rank_label

NY = ZoneInfo("America/New_York")

WINDOW_52W_DAYS = 366          # calendar days behind "52-week high"
WINDOW_3M_DAYS = 92            # calendar days behind "three months"
RV_WINDOW_DAYS = 20            # rv_snapshots.rv_20d: the realized-range window in sessions
STREET_DAYS = 90               # analyst actions counted in the street sentence
REACTION_WINDOW_SESSIONS = 5   # a report is "inside its reaction window" through this many sessions after it
BEAT_NOT_SIGNAL_SHARE = 50     # percent of beats followed by a fall at or above which a beat reads as no buy signal
MIN_QUARTERS = 4               # fewest stored quarters for the pattern and risk sentences
TIMING_PHRASE = {"bmo": "before the open", "amc": "after the close"}
SOURCE_NAMES = {"yfinance": "Yahoo Finance", "finnhub": "Finnhub", "company": "the company", "edgar": "EDGAR"}   # reader-facing names; receipts keep the technical ones
ACTION_WORDS = {"up": ("upgrade", "upgrades"), "down": ("downgrade", "downgrades"), "init": ("initiation", "initiations")}


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


# ── 1. position ──────────────────────────────────────────────────────────────

def range_phrase(rv_rank: float) -> tuple[str, str]:
    """("more active than 74%" | "quieter than 80%", the share shown): rv_rank is the percentile of the current 20-day
    realized volatility among the past year's 20-day windows."""
    if rv_rank >= 50:
        share = f"{rv_rank:.0f}%"
        return f"more active than {share}", share
    share = f"{100 - rv_rank:.0f}%"
    return f"quieter than {share}", share


def position_sentence(symbol: str, *, quote_price: float | None = None, quote_ts: int | None = None,
                      last_close: float | None = None, last_close_date: date | None = None,
                      high_52w: float | None = None, high_52w_date: date | None = None,
                      anchor_close_3m: float | None = None, anchor_date_3m: date | None = None,
                      rv_rank: float | None = None, rv_as_of: date | None = None) -> dict | None:
    """One price, the quote, dated by its last trade; the 52-week distance and the three-month change are the quote
    against the stored bars. The last close is a receipt, not a sentence."""
    inputs: list[dict] = []
    dates: list[date] = []
    bits: list[str] = []
    if quote_price is not None and quote_ts:
        t = fmt_quote_time(quote_ts)
        bits.append(f"{symbol} last traded at {fmt_money(quote_price)} ({t})")
        inputs += [_input("quote price", fmt_money(quote_price), t, "quote cache, dated by its last trade"), _input("quote time", t, t, "last trade")]
        dates.append(datetime.fromtimestamp(int(quote_ts), NY).date())
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
    text = ", ".join(bits) + "." if bits else ""
    label = rv_rank_label(rv_rank)
    if label and rv_as_of:
        phrase, share = range_phrase(rv_rank)
        rv_text = f"Its {RV_WINDOW_DAYS}-day realized range is {phrase} of its past year's {RV_WINDOW_DAYS}-day windows ({label.label} for this stock, as of {fmt_date(rv_as_of)})."
        text = f"{text} {rv_text}".strip()
        inputs += [_input("share of past-year windows", share, rv_as_of, f"rv_snapshots.rv_rank {rv_rank:.0f}"), _input("realized-range word", label.label, rv_as_of, f"thresholds: {label.rule}")]
        dates.append(rv_as_of)
    if not text:
        return None
    rule = (f"Price from the latest quote, dated by its last trade; the distance from the 52-week high (highest stored close over {WINDOW_52W_DAYS} calendar days) "
            f"and the change over {WINDOW_3M_DAYS} calendar days compare that quote with the stored Intrinio bars. Realized range: the {RV_WINDOW_DAYS}-day realized "
            "volatility as a percentile of the stock's own past year of such windows" + (f"; {label.label} means {label.rule}" if label else "") + ".")
    return _sentence("position", text, rule, max(dates) if dates else None, inputs)


# ── 2. catalyst ──────────────────────────────────────────────────────────────

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


def catalyst_sentence(*, today: date, next_date: date | None = None, confirmation: str | None = None, note: str | None = None,
                      source: str | None = None, timing: str | None = None,
                      implied_pct: float | None = None, chain_date: date | None = None, expiration: date | None = None,
                      avg_abs_1d: float | None = None, sample_n: int = 0, sample_as_of: date | None = None) -> dict | None:
    clauses: list[str] = []
    inputs: list[dict] = []
    dates: list[date] = []
    if next_date:
        days = (next_date - today).days
        bits = [f"Next earnings {fmt_date(next_date)}"]
        if timing in TIMING_PHRASE:
            bits.append(TIMING_PHRASE[timing])
        bits.append("today" if days == 0 else plural(days, "day away", "days away"))
        conf = confidence_phrase(confirmation, note, source)
        if conf:
            bits.append(conf)
            ev = evidence_phrase(note) if confirmation == "confirmed" else None
            if ev:
                inputs.append(_input("evidence", ev, next_date, "earnings calendar note"))
        clauses.append(", ".join(bits))
        inputs += [_input("next earnings date", fmt_date(next_date), next_date, source), _input("days away", days, today),
                   _input("report timing", timing or "unknown", next_date, "events.report_timing"), _input("confidence", confirmation or "none", next_date, note)]
        dates.append(next_date)
    if implied_pct is not None and chain_date:
        pct = fmt_pct(implied_pct * 100, signed=False)
        exp = f" through {fmt_date(expiration)}" if expiration else ""
        clauses.append(f"options imply a move of about ±{pct}{exp} (chain dated {fmt_date(chain_date)})")
        inputs += [_input("implied move", pct, chain_date, "ATM straddle over spot, services/implied_move"), _input("chain date", fmt_date(chain_date), chain_date, "options chain last trade")]
        if expiration:
            inputs.append(_input("expiration", fmt_date(expiration), expiration, "chosen expiry"))
        dates.append(chain_date)
    if avg_abs_1d is not None and sample_n > 0:
        avg = fmt_pct(avg_abs_1d, signed=False)
        clauses.append(f"its average 1-day move over {last_reports(sample_n)} has been ±{avg}")
        inputs += [_input("average absolute 1-day move", avg, sample_as_of, "historical_reactions, earnings rows with a 1-day move"), _input("reports in the sample", sample_n, sample_as_of)]
        if sample_as_of:
            dates.append(sample_as_of)
    if not clauses:
        return None
    text = "; ".join(clauses) + "."
    text = text[0].upper() + text[1:]
    rule = ("Next report from the stored earnings calendar (a confirmed date needs company evidence; an estimate names its source). "
            "Implied move: the at-the-money straddle over spot from the latest fresh options chain, dated by the chain. "
            "Average move: mean absolute 1-day move across stored earnings reactions.")
    return _sentence("catalyst", text, rule, max(dates) if dates else None, inputs)


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


def reported_sentence(*, today: date, event_date: date, timing: str | None = None, eps_actual: float | None = None,
                      eps_estimate: float | None = None, outcome: str | None = None, pct_change_1d: float | None = None,
                      bars_through: date | None = None) -> dict:
    """pct_change_1d is the stored row's move, or the move the builder computed from the stored bars with the seeder's
    own function when both bars exist; bars_through is the newest stored bar date, so a missing second bar is said."""
    inputs = [_input("report date", fmt_date(event_date), event_date, "events"), _input("report timing", timing or "unknown", event_date, "events.report_timing")]
    head = f"Reported {fmt_date(event_date)}" + (f" {TIMING_PHRASE[timing]}" if timing in TIMING_PHRASE else "")
    if eps_actual is not None and eps_estimate is not None:
        word = {"beat": "a beat", "miss": "a miss", "meet": "in line"}.get(outcome or "", None)
        eps = f"EPS {fmt_money(eps_actual)} against a {fmt_money(eps_estimate)} estimate" + (f", {word}" if word else "")
        inputs += [_input("EPS actual", fmt_money(eps_actual), event_date, "events.eps_actual (Finnhub, else Yahoo Finance), the night of the report"), _input("EPS estimate", fmt_money(eps_estimate), event_date, "events.eps_estimate"),
                   _input("outcome", outcome or "unknown", event_date, "actual above estimate is a beat")]
    else:
        eps = "EPS not yet reported to us"
    base_date, after_date = move_dates(event_date, timing)
    span = f"close {fmt_date(base_date)} to close {fmt_date(after_date)}" if base_date and after_date else None
    if pct_change_1d is not None and span:
        move = f"the 1-day move ({span}) was {fmt_pct(pct_change_1d)}"
        inputs += [_input("1-day move", fmt_pct(pct_change_1d), after_date, "stored bars through the seeder's window (close to close)"),
                   _input("1-day move window", span, after_date, "trading calendar")]
    elif after_date is None:
        move = "the 1-day move is recorded once the report timing is known"
    elif after_date == today:
        move = "the 1-day move settles at today's close"
        inputs.append(_input("settlement session", fmt_date(after_date), after_date, "trading calendar"))
    elif after_date > today:
        move = f"the 1-day move settles at the close on {fmt_date(after_date)}"
        inputs.append(_input("settlement session", fmt_date(after_date), after_date, "trading calendar"))
    else:
        move = f"the 1-day move ({span}) is not yet stored"
        inputs.append(_input("newest stored bar", fmt_date(bars_through) if bars_through else "none", bars_through, "price_bars_shadow"))
    rule = (f"Shown through {REACTION_WINDOW_SESSIONS} sessions after a report. EPS from the event row, fetched the night of the report; beat or miss is actual against estimate. The 1-day move is the seeder's window on the "
            "stored bars: close of the report day to the next session's close after an after-close report, the prior close to the report day's close before the open; "
            "it settles at the close that completes that window.")
    return _sentence("catalyst", f"{head}: {eps}; {move}.", rule, event_date, inputs)


# ── 3. pattern ───────────────────────────────────────────────────────────────

def pattern_sentence(*, total: int, beat_count: int, fell_after_beat: int, as_of: date | None, basis_excluded: int = 0) -> dict | None:
    if total < MIN_QUARTERS or beat_count < 1:
        return None
    share = fell_after_beat / beat_count * 100
    share_txt = f"{share:.0f}%"
    tail = ("so a beat alone has not been a buy signal" if share >= BEAT_NOT_SIGNAL_SHARE
            else "so a beat has usually been followed by a gain")
    text = (f"Beat estimates in {beat_count} of {last_reports(total)} and fell the next session after "
            f"{fell_after_beat} of those {beat_count} beats ({share_txt}), {tail}.")
    inputs = [_input("reports in the sample", total, as_of, "historical_reactions, earnings rows with a 1-day move"), _input("beats", beat_count, as_of, "EPS actual above estimate"),
              _input("beats followed by a fall", fell_after_beat, as_of, "1-day move below zero"), _input("share", share_txt, as_of)]
    if basis_excluded:
        inputs.append(_input("quarters excluded", basis_excluded, as_of, "EPS basis unclear"))
    rule = (f"Earnings quarters with a stored 1-day move (at least {MIN_QUARTERS}); a beat is EPS actual above estimate; 'fell' is a negative 1-day move; "
            f"a share of {BEAT_NOT_SIGNAL_SHARE}% or more reads as no buy signal" + (f"; {basis_excluded} quarter(s) with an unclear EPS basis excluded" if basis_excluded else "") + ".")
    return _sentence("pattern", text, rule, as_of, inputs)


# ── 4. street ────────────────────────────────────────────────────────────────

def street_sentence(*, today: date, actions: list[dict], median_1d_upgrade: float | None = None, upgrade_sessions: int | None = None,
                    stats_as_of: date | None = None) -> dict | None:
    since = today - timedelta(days=STREET_DAYS)
    recent = [a for a in actions if a.get("date") and since <= a["date"] <= today]
    counts = {k: sum(1 for a in recent if a.get("action") == k) for k in ACTION_WORDS}
    targets = [float(a["price_target"]) for a in recent if a.get("price_target")]
    inputs: list[dict] = []
    clauses: list[str] = []
    newest = max((a["date"] for a in recent), default=None)
    if recent:
        parts = [plural(counts[k], *ACTION_WORDS[k]) for k in ("up", "down", "init") if counts[k]]      # only what happened is named
        if not parts:
            listed = "no upgrades, downgrades or initiations"                    # only maintains or reiterations in the window
        else:
            listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
        tally = f"Over the last {STREET_DAYS} days analysts made {listed}"
        if targets:
            med = fmt_money(median(targets))
            tally += f", median price target {med}"
            inputs.append(_input("median price target", med, newest, f"{len(targets)} action(s) with a target"))
        clauses.append(tally)
        for k in ("up", "down", "init"):
            inputs.append(_input(ACTION_WORDS[k][1], counts[k], newest, "events, analyst_action"))
        inputs.append(_input("window", f"{STREET_DAYS} days", today))
    if median_1d_upgrade is not None and upgrade_sessions:
        m = fmt_pct(median_1d_upgrade)
        clause = f"on upgrade days this stock's median move has been {m} across {plural(upgrade_sessions, 'upgrade session', 'upgrade sessions')}"
        clauses.append(clause if clauses else clause[0].upper() + clause[1:])
        inputs += [_input("median move on upgrade days", m, stats_as_of, "analyst_reaction_stats.median_1d_upgrade"), _input("upgrade sessions", upgrade_sessions, stats_as_of, "analyst_reaction_stats")]
    if not clauses:
        return None
    dates = [d for d in (newest, stats_as_of) if d]
    rule = (f"Analyst actions stored in the last {STREET_DAYS} days (upgrades, downgrades, initiations; the median of any price targets they carried). "
            "Upgrade-day move: the stock's median close-to-close move on sessions with an upgrade, from the stored analyst stats.")
    return _sentence("street", "; ".join(clauses) + ".", rule, max(dates) if dates else None, inputs)


# ── 5. risk ──────────────────────────────────────────────────────────────────

def risk_sentence(*, moves: list[tuple[date, float]]) -> dict | None:
    if len(moves) < MIN_QUARTERS:
        return None
    worst = min(moves, key=lambda m: m[1])
    best = max(moves, key=lambda m: m[1])
    as_of = max(d for d, _ in moves)
    text = (f"Across {last_reports(len(moves))}, the worst 1-day move was {fmt_pct(worst[1])} ({fmt_date(worst[0])}) "
            f"and the best {fmt_pct(best[1])} ({fmt_date(best[0])}).")
    inputs = [_input("reports in the sample", len(moves), as_of, "historical_reactions, earnings rows with a 1-day move"),
              _input("worst 1-day move", fmt_pct(worst[1]), worst[0]), _input("best 1-day move", fmt_pct(best[1]), best[0])]
    rule = f"Lowest and highest stored 1-day moves after earnings reports (at least {MIN_QUARTERS} stored quarters), each dated by its report."
    return _sentence("risk", text, rule, as_of, inputs)


def paragraph(sentences: list[dict]) -> str:
    return " ".join(s["text"] for s in sentences)
