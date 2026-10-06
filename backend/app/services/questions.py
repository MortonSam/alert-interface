"""The question strip: up to four questions an investor looking at this stock is likely already asking, chosen by the
stock's own data, each answered in at most three short sentences from stored rows. No model writes anything.

Each answer is {key, question, data, idea, inputs, as_of, rule}: `data` is what this stock's rows show (one or two
sentences, every number an input with its receipt), `idea` is the plain-words explanation for someone new. A question
whose data is missing, stale, or rests on fewer than MIN_REPORTS reports or MIN_SESSIONS sessions never appears. The
catalog order is the priority order; the builder shows the first MAX_QUESTIONS that qualify. Two evergreen questions (the
usual move on earnings, volatility against the stock's own year) follow the six event questions, so every stock with at
least MIN_REPORTS reports shows at least three.
"""
from __future__ import annotations

from datetime import date

from app.services.briefing import TIMING_PHRASE, _input, fmt_date, fmt_money, fmt_pct, last_reports, plural, short_name

MAX_QUESTIONS = 4
MIN_REPORTS = 8               # fewest past reports behind a report-based answer
MIN_SESSIONS = 8              # fewest sessions behind a session-based answer
BEAT_FELL_SHARE = 50          # percent of beats followed by a fall at or above which the question is asked
BIG_MOVE_MULTIPLE = 4         # a daily move at least this many times the median absolute daily move is big
RANK_YEARS = 5                # the daily-move rank is against this many years of sessions
UPGRADE_DAYS = 30             # an upgrade this recent raises the analyst question
EX_DIV_DAYS = 14              # an ex-dividend date this close raises the dividend question
NEXT_WITHIN_DAYS = 45         # a report this close, with a fresh implied move, raises the expected-move question


def _q(key: str, question: str, data: str, idea: str, inputs: list[dict], as_of: date | None, rule: str, as_of_kind: str = "observed") -> dict:
    """as_of is the day we knew the fact (a bar, a chain, a stored report, a refresh), never a day still ahead; as_of_kind is
    observed (a measurement), estimated (a projection, dated by the refresh that stored it) or declared (dated by the declaration)."""
    return {"key": key, "question": question, "data": data, "idea": idea, "inputs": inputs, "as_of": as_of.isoformat() if as_of else None,
            "as_of_kind": as_of_kind, "rule": rule}


# 1 ─────────────────────────────────────────────────────────────────────────────
def q_reaction_normal(*, name: str, symbol: str, event_date: date, timing: str | None, move_pct: float, typical_abs: float,
                      larger_count: int, n_reports: int, sample_as_of: date | None) -> dict | None:
    """Inside a report's reaction window: the 1-day move against the typical one and its rank among past reports."""
    if n_reports < MIN_REPORTS:
        return None
    when = "that session" if timing == "bmo" else "the next session"
    data = (f"{symbol} moved {fmt_pct(move_pct)} {when} after its {fmt_date(event_date)} report, against a typical ±{fmt_pct(typical_abs, signed=False)} "
            f"over {last_reports(n_reports)}; {plural(larger_count, 'of those reports moved it more', 'of those reports moved it more')}.")
    idea = ("A 1-day move is the close-to-close change over the first session that trades on the news; a report released after the close "
            "is priced the next morning, so that next session is the one that counts.")
    inputs = [_input("1-day move", fmt_pct(move_pct), event_date, "stored bars through the seeder's window"), _input("report date", fmt_date(event_date), event_date, "events"),
              _input("typical move", f"±{fmt_pct(typical_abs, signed=False)}", sample_as_of, "mean absolute 1-day move, historical_reactions"),
              _input("reports moving more", larger_count, sample_as_of, "past reports with a larger absolute 1-day move"), _input("reports in the sample", n_reports, sample_as_of)]
    return _q("reaction_normal", f"Was {name}'s move after this report normal?", data, idea, inputs, event_date,
              f"Shown through five sessions after a report with at least {MIN_REPORTS} past reports; the move is the seeder's 1-day window on the stored bars; "
              "typical is the mean absolute 1-day move; the rank counts past reports with a larger absolute move.")


# 2 ─────────────────────────────────────────────────────────────────────────────
def q_implied_big(*, name: str, symbol: str, implied_pct: float, chain_date: date, next_date: date, typical_abs: float, n_reports: int,
                  sample_as_of: date | None) -> dict | None:
    """A report within NEXT_WITHIN_DAYS with a fresh implied move: the options' move against the typical one."""
    if n_reports < MIN_REPORTS:
        return None
    imp = fmt_pct(implied_pct * 100, signed=False)
    typ = fmt_pct(typical_abs, signed=False)
    ratio = (implied_pct * 100) / typical_abs if typical_abs else None
    verdict = "more than usual" if ratio and ratio > 1.15 else "less than usual" if ratio and ratio < 0.85 else "about its usual"
    data = (f"Options price a move of about ±{imp} for the {fmt_date(next_date)} report; over {last_reports(n_reports)} {symbol} has moved ±{typ} on average, "
            f"so the market is pricing {verdict}.")
    idea = ("The implied move is what a straddle costs: the price the options market puts on uncertainty. It tends to run above the move that "
            "actually follows, because option sellers charge for the risk of being wrong.")
    inputs = [_input("implied move", f"±{imp}", chain_date, "ATM straddle over spot, latest fresh chain"), _input("chain date", fmt_date(chain_date), chain_date, "options chain last trade"),
              _input("report date", fmt_date(next_date), next_date, "events"), _input("typical move", f"±{typ}", sample_as_of, "mean absolute 1-day move, historical_reactions"),
              _input("reports in the sample", n_reports, sample_as_of)]
    return _q("implied_big", f"Is a ±{imp} expected move big for {name}?", data, idea, inputs, chain_date,
              f"A report within {NEXT_WITHIN_DAYS} days and a fresh chain; at least {MIN_REPORTS} past reports; more or less than usual means the implied move is "
              "over 15% above or below the mean absolute 1-day move.")


# 3 ─────────────────────────────────────────────────────────────────────────────
def q_beat_fell(*, name: str, symbol: str, beats: int, fell: int, as_of: date | None) -> dict | None:
    """Beats followed by a fall at or above BEAT_FELL_SHARE, on at least MIN_REPORTS beats."""
    if beats < MIN_REPORTS:
        return None
    share = fell / beats * 100
    if share < BEAT_FELL_SHARE:
        return None
    share_txt = f"{share:.0f}%"
    data = f"{symbol} fell the next session after {fell} of its last {beats} beats ({share_txt})."
    idea = ("By report day the price usually already reflects an expected beat, so what moves the stock is the size of the surprise against the estimate "
            "and what the company says about the months ahead.")
    inputs = [_input("beats", beats, as_of, "EPS actual above estimate, historical_reactions"), _input("beats followed by a fall", fell, as_of, "1-day move below zero"),
              _input("share", share_txt, as_of)]
    return _q("beat_fell", f"Why does {name} sometimes fall after beating estimates?", data, idea, inputs, as_of,
              f"Asked when at least {BEAT_FELL_SHARE}% of at least {MIN_REPORTS} beats were followed by a negative 1-day move.")


# 4 ─────────────────────────────────────────────────────────────────────────────
def q_big_move(*, name: str, symbol: str, move_date: date, move_pct: float, typical_abs: float, multiple: float, smaller_share: float,
               n_sessions: int) -> dict | None:
    """A big non-earnings daily move in the last 20 sessions: its rank among five years of daily moves. No cause is stated."""
    if n_sessions < MIN_SESSIONS or multiple < BIG_MOVE_MULTIPLE:
        return None
    mult = f"{multiple:.0f}"
    share = f"{smaller_share:.1f}%"
    data = (f"On {fmt_date(move_date)} {symbol} moved {fmt_pct(move_pct)}, about {mult} times a typical day for it and larger than {share} of its daily moves "
            f"over the past {RANK_YEARS} years ({n_sessions:,} sessions).")
    idea = ("Realized volatility measures how much a stock actually moves from one close to the next; a single day like this can dominate a 20-day reading "
            "for weeks after it.")
    inputs = [_input("daily move", fmt_pct(move_pct), move_date, "price_bars_shadow, close to close"), _input("multiple of a typical day", mult, move_date, "against the median absolute daily move of the past year"),
              _input("typical daily move", f"±{fmt_pct(typical_abs, signed=False)}", move_date, "median absolute daily move, past year"),
              _input("share of daily moves smaller", share, move_date, f"all stored daily moves over {RANK_YEARS} years"), _input("sessions compared", f"{n_sessions:,}", move_date)]
    return _q("big_move", f"How unusual was {name}'s move on {fmt_date(move_date)}?", data, idea, inputs, move_date,
              f"The largest daily move of the last 20 sessions off earnings dates, at least {BIG_MOVE_MULTIPLE} times the median absolute daily move, ranked against "
              f"every stored daily move of the past {RANK_YEARS} years. No cause is stated: this system holds no news.")


# 5 ─────────────────────────────────────────────────────────────────────────────
def q_upgrades(*, name: str, symbol: str, upgrades_30d: int, upgrade_sessions: int, median_1d: float, continuation_pct: float | None, sample_5d: int,
               stats_as_of: date | None, newest_upgrade: date | None) -> dict | None:
    """At least one upgrade in the last UPGRADE_DAYS and at least MIN_SESSIONS upgrade sessions on record."""
    if upgrades_30d < 1 or upgrade_sessions < MIN_SESSIONS:
        return None
    med = fmt_pct(median_1d)
    data = f"On its {upgrade_sessions} past upgrade days {symbol}'s median move was {med}"
    inputs = [_input("recent upgrades", upgrades_30d, newest_upgrade, f"events, analyst_action up, last {UPGRADE_DAYS} days"),
              _input("upgrade sessions", upgrade_sessions, stats_as_of, "analyst_reaction_stats"), _input("median upgrade-day move", med, stats_as_of, "analyst_reaction_stats.median_1d_upgrade")]
    if continuation_pct is not None and sample_5d >= MIN_SESSIONS:
        cont = f"{continuation_pct:.0f}%"
        data += f", and in {cont} of them the five-session move kept the first day's direction."
        inputs.append(_input("direction kept after five sessions", cont, stats_as_of, f"analyst_reaction_stats.upgrade_5d_continuation_pct over {sample_5d} sessions"))
    else:
        data += "."
    idea = "An upgrade can move a stock because it changes what some investors expect of it; the move often fades once the new view is priced in."
    return _q("upgrades", f"Do analyst upgrades move {name}?", data, idea, inputs, newest_upgrade or stats_as_of,
              f"Asked after an upgrade in the last {UPGRADE_DAYS} days with at least {MIN_SESSIONS} upgrade sessions on record; the median is of close-to-close moves "
              "on sessions with an upgrade; the follow-through share counts five-session moves with the same sign as the first day's.")


# 6 ─────────────────────────────────────────────────────────────────────────────
def q_ex_dividend(*, name: str, symbol: str, ex_date: date, amount: float | None, today: date, stored_on: date | None = None,
                  declared_on: date | None = None) -> dict | None:
    """An ex-dividend date within EX_DIV_DAYS. Dated by the declaration when one is held, else as an estimate dated by the refresh
    that stored the amount; the ex-date itself is the event, never the as-of."""
    days = (ex_date - today).days
    if days < 0 or days > EX_DIV_DAYS:
        return None
    amt = f" with a {fmt_money(amount)} per-share dividend" if amount else ""
    data = f"{symbol} goes ex-dividend on {fmt_date(ex_date)}{amt}."
    idea = "On the ex-dividend date the price typically opens lower by about the dividend, because buyers from that day on no longer receive that payment."
    knew = declared_on or stored_on or today
    inputs = [_input("ex-dividend date", fmt_date(ex_date), knew, "events, ex_dividend")]
    if amount:
        inputs.append(_input("dividend per share", fmt_money(amount), knew, "declared" if declared_on else "the last per-payment amount (Intrinio's bars, else yfinance's last declared payment)"))
    return _q("ex_dividend", f"What happens to {name}'s price on the ex-dividend date?", data, idea, inputs, knew,
              f"Asked when a stored ex-dividend date is within {EX_DIV_DAYS} days; dated by the declaration when held, else by the refresh that stored the amount.",
              as_of_kind="declared" if declared_on else "estimated")


# 7 ─────────────────────────────────────────────────────────────────────────────
def q_usual_move(*, name: str, symbol: str, typical_abs: float, n_reports: int, best: tuple[date, float], worst: tuple[date, float],
                 sample_as_of: date | None) -> dict | None:
    """Evergreen: the typical 1-day move over past reports with the largest up and down moves."""
    if n_reports < MIN_REPORTS:
        return None
    typ = fmt_pct(typical_abs, signed=False)
    data = (f"Over {last_reports(n_reports)} {symbol} has moved ±{typ} on average the session after reporting; its largest were {fmt_pct(best[1])} "
            f"({fmt_date(best[0])}) and {fmt_pct(worst[1])} ({fmt_date(worst[0])}).")
    idea = ("The typical move is the average size of the stock's past reactions, up or down; it is the yardstick an expected move is measured "
            "against, because the options market is pricing a move of some size, not a direction.")
    inputs = [_input("typical move", f"±{typ}", sample_as_of, "mean absolute 1-day move, historical_reactions"), _input("reports in the sample", n_reports, sample_as_of),
              _input("largest up move", fmt_pct(best[1]), best[0], "historical_reactions"), _input("largest down move", fmt_pct(worst[1]), worst[0], "historical_reactions")]
    return _q("usual_move", f"How much does {name} usually move on earnings?", data, idea, inputs, sample_as_of,
              f"At least {MIN_REPORTS} past reports with a 1-day move; typical is the mean absolute move; the largest are the extremes of the same sample.")


# 8 ─────────────────────────────────────────────────────────────────────────────
def q_volatile_now(*, name: str, symbol: str, rv_20d: float, rv_rank: float, sample_days: int, as_of: date) -> dict | None:
    """Evergreen: the current 20-day realized volatility against the stock's own past year."""
    if sample_days < MIN_SESSIONS:
        return None
    rv = fmt_pct(rv_20d * 100, signed=False)
    share = f"{rv_rank:.0f}%" if rv_rank >= 50 else f"{100 - rv_rank:.0f}%"
    phrase = f"more active than {share}" if rv_rank >= 50 else f"quieter than {share}"
    data = f"{symbol}'s realized volatility over the last 20 sessions is {rv} annualized, {phrase} of its own 20-day windows over the past year."
    idea = ("Realized volatility measures how much a stock actually moved from one close to the next; a stock is only \"volatile\" relative to its own "
            "normal, so the comparison that matters is with its own past year.")
    inputs = [_input("20-day realized volatility", rv, as_of, "rv_snapshots.rv_20d, annualized"), _input("share of past-year windows", share, as_of, f"rv_snapshots.rv_rank {rv_rank:.0f}"),
              _input("sessions in the past year", sample_days, as_of, "rv_snapshots.sample_days")]
    return _q("volatile_now", f"Is {name} more volatile than usual right now?", data, idea, inputs, as_of,
              f"The latest servable realized-volatility snapshot with at least {MIN_SESSIONS} sessions; the rank is the percentile of the current 20-day value among the past year's windows.")


def choose(candidates: list[dict | None]) -> list[dict]:
    """The first MAX_QUESTIONS answers that qualify, in catalog order."""
    return [c for c in candidates if c][:MAX_QUESTIONS]


__all__ = ["choose", "q_reaction_normal", "q_implied_big", "q_beat_fell", "q_big_move", "q_upgrades", "q_ex_dividend", "q_usual_move", "q_volatile_now", "short_name"]
