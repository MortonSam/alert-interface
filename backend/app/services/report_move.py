"""The part of an implied move that belongs to the report alone, from expirations of one stored chain date, by one of two methods.

Pair (the expirations around the report): s1 is the at-the-money IV of the last expiration before the report (one that does not
capture it, chain_shadow.counts_for_report), s2 the first that captures it, T2 the years from the chain date to s2's expiration
(iv_solver.DAY_COUNT). E = sqrt(T2 x (s2^2 - s1^2)). Used only when s1's expiration is at least PAIR_MIN_PRE_SESSIONS trading days
after the chain date and s2's is within PAIR_MAX_POST_DAYS of the report: a pre leg days away against a post leg weeks out compares
a few days' volatility with a month's, which is not the report.

Term (the first two expirations after the report): s2 and T2 as above, s3 and T3 the next expiration after s2's. The normal
variance without the report is base = (s3^2 x T3 - s2^2 x T2) / (T3 - T2), the forward variance between the two, which holds no
report; E = sqrt(T2 x (s2^2 - base)). A base at or below zero is not a variance and gives no E.

The pair is tried first when it qualifies, then the term method; the first positive E wins. The report-only expected move is
REPORT_SHARE x E (a straddle prices about 0.8 of a standard deviation). When neither method gives a positive E the options do not
separate a report move and none is stated.

Every IV is solved here (iv_solver.solve_atm) from the chains' own mids, spot (`underlying_price`, the close on the chain date) and
the stored rate on that date. Any change to the formula or its inputs bumps REPORT_MOVE_VERSION.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

from app.services import chain_store
from app.services.chain_shadow import counts_for_report
from app.services.trading_calendar import nth_trading_day_after
from app.services.iv_solver import nonstandard_mids, solve_atm, time_to_expiry

REPORT_MOVE_VERSION = 2       # 2: the pair only when it qualifies, else the first two expirations after the report
REPORT_SHARE = 0.80            # expected absolute move of a normal day, in standard deviations (sqrt(2/pi) = 0.798)
PAIR_MIN_PRE_SESSIONS = 5      # the pair's pre-report expiration is at least this many trading days after the chain date
PAIR_MAX_POST_DAYS = 21        # and its post-report expiration within this many calendar days of the report

PAIR = "pair"                  # methods
TERM = "term"

# why no report move is stated; every state has a sentence in move_comparison.REPORT_MOVE_ABSENT
OK = "ok"
NOT_SEPARATED = "not_separated"               # a method was computed and none gave a positive E
NO_LEGS = "no_legs"                           # the pair does not qualify and no second expiration after the report is stored
NO_CHAIN = "no_chain"                         # no fresh stored chain captures the report
MIXED_DATES = "mixed_dates"                   # the legs a method needs were stored on different days
NO_IV = "no_iv"                               # an ATM IV could not be solved on a leg either method needs
STATES = (OK, NOT_SEPARATED, NO_LEGS, NO_CHAIN, MIXED_DATES, NO_IV)


def report_move_pct(s1: float, s2: float, t2: float) -> float | None:
    """Pure: REPORT_SHARE x sqrt(T2 x (s2^2 - s1^2)) as a 0-1 decimal, or None when s2 is not above s1 or T2 is not positive."""
    if t2 <= 0 or s2 <= s1:
        return None
    return REPORT_SHARE * math.sqrt(t2 * (s2 * s2 - s1 * s1))


def term_move_pct(s2: float, t2: float, s3: float, t3: float) -> float | None:
    """Pure: the term method, REPORT_SHARE x sqrt(T2 x (s2^2 - base)) with base = (s3^2 T3 - s2^2 T2) / (T3 - T2), as a 0-1
    decimal; None when T3 is not after T2, base is not a positive variance, or s2^2 is not above it."""
    if t2 <= 0 or t3 <= t2:
        return None
    base = (s3 * s3 * t3 - s2 * s2 * t2) / (t3 - t2)
    if base <= 0 or s2 * s2 <= base:
        return None
    return REPORT_SHARE * math.sqrt(t2 * (s2 * s2 - base))


def term_base(s2: float, t2: float, s3: float, t3: float) -> float | None:
    return None if t3 <= t2 else (s3 * s3 * t3 - s2 * s2 * t2) / (t3 - t2)


def pick_legs(expirations: list[str], report_date: str, timing: str | None, chain_date: str) -> tuple[str | None, str | None, str | None]:
    """Pure: (the last expiration after the chain date that does not capture the report, the first that does, the one after it)."""
    later = sorted(e for e in expirations if e > chain_date)
    pre = [e for e in later if not counts_for_report(e, report_date, timing)]
    posts = [e for e in later if counts_for_report(e, report_date, timing)]
    return (pre[-1] if pre else None), (posts[0] if posts else None), (posts[1] if len(posts) > 1 else None)


def pair_qualifies(pre: str | None, post: str | None, report_date: str, chain_date: str) -> bool:
    """Pure: the pair is used only when the pre-report expiration is at least PAIR_MIN_PRE_SESSIONS trading days after the chain
    date and the post-report one within PAIR_MAX_POST_DAYS days of the report."""
    if not pre or not post:
        return False
    far_enough = date.fromisoformat(pre) >= nth_trading_day_after(date.fromisoformat(chain_date), PAIR_MIN_PRE_SESSIONS)
    close_enough = (date.fromisoformat(post) - date.fromisoformat(report_date)).days <= PAIR_MAX_POST_DAYS
    return far_enough and close_enough


@dataclass(frozen=True)
class Leg:
    expiration: str
    chain_date: str
    atm_strike: float | None
    atm_iv: float | None


@dataclass(frozen=True)
class ReportMove:
    state: str
    pct: float | None = None            # the report-only expected move, 0-1 decimal
    e: float | None = None              # sqrt(T2 x (s2^2 - s1^2)), before REPORT_SHARE
    t2_years: float | None = None
    before: Leg | None = None           # s1's expiration (the pair)
    after: Leg | None = None            # s2's expiration (both methods)
    report_date: str | None = None
    version: int = REPORT_MOVE_VERSION
    method: str | None = None           # PAIR or TERM when a move is stated
    later: Leg | None = None            # s3's expiration (the term method)
    t3_years: float | None = None
    base_variance: float | None = None  # the term method's normal variance, annualized

    def as_dict(self) -> dict:
        return asdict(self)


def _solve(chain: dict, chain_date: date, exp: str, rate: float) -> tuple[float | None, float | None]:
    spot = chain.get("underlying_price")
    if not spot:
        return None, None
    a = solve_atm(chain, float(spot), chain_date, date.fromisoformat(exp), rate)
    if nonstandard_mids(a.call_mid, a.put_mid):
        return a.strike, None
    return a.strike, a.atm_iv


async def report_move(db, sym: str, report_date: date | str, today: date | None = None) -> ReportMove:
    """The report-only expected move for `sym`'s report on `report_date`, from the serving source's stored chains, with receipts."""
    from app.services.rates import rate_on
    rd = report_date.isoformat() if isinstance(report_date, date) else str(report_date)[:10]
    post_exp = await chain_store.pick_expiration(db, sym, rd)
    post_got = await chain_store.get_chain(db, sym, post_exp) if post_exp else None
    if not post_got or not post_got[1] or not chain_store.is_fresh(post_got[1], today=today):
        return ReportMove(NO_CHAIN, report_date=rd)
    chain_day = str(post_got[1])[:10]
    timing = await chain_store.report_timing_on(db, sym, rd)
    timing = None if timing is chain_store._NO_REPORT else timing
    pre_exp, post_exp2, later_exp = pick_legs(await chain_store.get_ingested_expirations(db, sym), rd, timing, chain_day)
    if post_exp2 != post_exp:
        return ReportMove(NO_CHAIN, report_date=rd)
    use_pair = pair_qualifies(pre_exp, post_exp, rd, chain_day)
    if not use_pair and later_exp is None:
        return ReportMove(NO_LEGS, report_date=rd)
    cd = date.fromisoformat(chain_day)
    rate = await rate_on(db, cd)
    if rate.rate is None:
        return ReportMove(NO_IV, report_date=rd)

    async def leg(exp: str) -> Leg | None:
        """The leg on the post leg's chain date, or None when that expiration was stored on another day."""
        got = post_got if exp == post_exp else await chain_store.get_chain(db, sym, exp)
        if not got or not got[1] or str(got[1])[:10] != chain_day:
            return None
        k, iv = _solve(got[0], cd, exp, rate.rate)
        return Leg(exp, chain_day, k, iv)

    after = await leg(post_exp)
    if after is None or after.atm_iv is None:
        return ReportMove(NO_IV, after=after, report_date=rd)
    _, t2 = time_to_expiry(cd, date.fromisoformat(post_exp))
    computed, mixed, no_iv = False, False, False
    before = later = None
    t3 = base = None
    if use_pair:
        before = await leg(pre_exp)
        if before is None:
            mixed = True
        elif before.atm_iv is None:
            no_iv = True
        else:
            computed = True
            pct = report_move_pct(before.atm_iv, after.atm_iv, t2)
            if pct is not None:
                return ReportMove(OK, pct=pct, e=pct / REPORT_SHARE, t2_years=t2, before=before, after=after, report_date=rd, method=PAIR)
    if later_exp is not None:
        later = await leg(later_exp)
        if later is None:
            mixed = True
        elif later.atm_iv is None:
            no_iv = True
        else:
            computed = True
            _, t3 = time_to_expiry(cd, date.fromisoformat(later_exp))
            base = term_base(after.atm_iv, t2, later.atm_iv, t3)
            pct = term_move_pct(after.atm_iv, t2, later.atm_iv, t3)
            if pct is not None:
                return ReportMove(OK, pct=pct, e=pct / REPORT_SHARE, t2_years=t2, before=before, after=after, report_date=rd,
                                  method=TERM, later=later, t3_years=t3, base_variance=base)
    state = NOT_SEPARATED if computed else MIXED_DATES if mixed else NO_IV if no_iv else NO_LEGS
    return ReportMove(state, t2_years=t2, before=before, after=after, report_date=rd, later=later, t3_years=t3, base_variance=base)


async def report_move_view(db, sym: str, report_date: date | str, today: date | None = None, held_facts=(),
                           typical: tuple[float | None, int] | None = None) -> dict:
    """The report move as every surface states it (the ticker page's verdict, Discover's reporting-soon line, the strip question,
    the Overview clause and Ask Ivy's facts): the move, its receipts, the typical first-day move it is compared with
    (routers/discover._batch_conditional_stats unless `typical` = (percent, reports) is passed), the comparison words and the one
    sentence (services/move_comparison). A held implied move or report date gives {}; a held typical move drops the comparison.

        state     the ReportMove state; `comparison` is REPORT_MOVE_ABSENT's sentence when it is not OK
        pct       the move as a 0-1 decimal, rep the percent rounded to 0.1 as stated
    """
    from app.services.move_comparison import REPORT_MOVE_ABSENT, report_sentence, report_verdict
    held = set(held_facts)
    if {"implied_move", "report_date"} & held:
        return {}
    rm = await report_move(db, sym, report_date, today)
    out = {"state": rm.state, "move": rm, "report_move": rm.as_dict()}
    if rm.state != OK:
        return {**out, "comparison": REPORT_MOVE_ABSENT[rm.state]}
    rep = round(rm.pct * 100, 1)
    typ, n = None, 0
    if "typical_move" not in held:
        if typical is None:
            from app.routers.discover import _batch_conditional_stats
            cond = (await _batch_conditional_stats(db, [sym])).get(sym)
            typical = (float(cond["avg_abs_1d"]), int(cond.get("total") or 0)) if cond and cond.get("avg_abs_1d") else (None, 0)
        typ = round(typical[0], 1) if typical[0] else None
        n = typical[1] if typ is not None else 0
    verdict = report_verdict(rep, typ, n)
    chain_day = date.fromisoformat(rm.after.chain_date)
    return {**out, "pct": rm.pct, "rep": rep, "chain_date": chain_day, "typical_move_pct": typ, "typical_n": n or None,
            "move_comparison": verdict, "comparison": report_sentence(rep, typ if verdict else None, verdict, chain_day)}
