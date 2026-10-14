"""The part of an implied move that belongs to the report alone, from two expirations of one stored chain date.

s1 is the at-the-money IV of the last expiration before the report (one that does not capture it, chain_shadow.counts_for_report),
s2 the first expiration that captures it, T2 the years from the chain date to s2's expiration (iv_solver.DAY_COUNT). The extra
variance the report adds is T2 x (s2^2 - s1^2); its square root E is the report's one-day standard deviation, and the report-only
expected move is REPORT_SHARE x E (a straddle prices about 0.8 of a standard deviation). With no expiration before the report, or s2
not above s1, the options do not separate a report move and none is stated.

Both IVs are solved here (iv_solver.solve_atm) from the chains' own mids, spot (`underlying_price`, the close on the chain date) and
the stored rate on that date. Any change to the formula or its inputs bumps REPORT_MOVE_VERSION.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

from app.services import chain_store
from app.services.chain_shadow import counts_for_report
from app.services.iv_solver import nonstandard_mids, solve_atm, time_to_expiry

REPORT_MOVE_VERSION = 1
REPORT_SHARE = 0.80            # expected absolute move of a normal day, in standard deviations (sqrt(2/pi) = 0.798)

# why no report move is stated; every state has a sentence in move_comparison.REPORT_MOVE_ABSENT
OK = "ok"
NO_PRE_EXPIRATION = "no_pre_expiration"       # no stored expiration between the chain date and the report
NOT_SEPARATED = "not_separated"               # s2 is not above s1
NO_CHAIN = "no_chain"                         # no fresh stored chain captures the report
MIXED_DATES = "mixed_dates"                   # the two expirations were stored on different days
NO_IV = "no_iv"                               # an ATM IV could not be solved on either leg
STATES = (OK, NO_PRE_EXPIRATION, NOT_SEPARATED, NO_CHAIN, MIXED_DATES, NO_IV)


def report_move_pct(s1: float, s2: float, t2: float) -> float | None:
    """Pure: REPORT_SHARE x sqrt(T2 x (s2^2 - s1^2)) as a 0-1 decimal, or None when s2 is not above s1 or T2 is not positive."""
    if t2 <= 0 or s2 <= s1:
        return None
    return REPORT_SHARE * math.sqrt(t2 * (s2 * s2 - s1 * s1))


def pick_legs(expirations: list[str], report_date: str, timing: str | None, chain_date: str) -> tuple[str | None, str | None]:
    """Pure: (the last expiration after the chain date that does not capture the report, the first that does)."""
    later = sorted(e for e in expirations if e > chain_date)
    pre = [e for e in later if not counts_for_report(e, report_date, timing)]
    post = next((e for e in later if counts_for_report(e, report_date, timing)), None)
    return (pre[-1] if pre else None), post


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
    before: Leg | None = None           # s1's expiration
    after: Leg | None = None            # s2's expiration
    report_date: str | None = None
    version: int = REPORT_MOVE_VERSION

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
    pre_exp, post_exp2 = pick_legs(await chain_store.get_ingested_expirations(db, sym), rd, timing, chain_day)
    if post_exp2 != post_exp:
        return ReportMove(NO_CHAIN, report_date=rd)
    if pre_exp is None:
        return ReportMove(NO_PRE_EXPIRATION, report_date=rd)
    pre_got = await chain_store.get_chain(db, sym, pre_exp)
    if not pre_got or not pre_got[1] or str(pre_got[1])[:10] != chain_day:
        return ReportMove(MIXED_DATES, report_date=rd)
    cd = date.fromisoformat(chain_day)
    rate = await rate_on(db, cd)
    if rate.rate is None:
        return ReportMove(NO_IV, report_date=rd)
    k1, s1 = _solve(pre_got[0], cd, pre_exp, rate.rate)
    k2, s2 = _solve(post_got[0], cd, post_exp, rate.rate)
    before, after = Leg(pre_exp, chain_day, k1, s1), Leg(post_exp, chain_day, k2, s2)
    if s1 is None or s2 is None:
        return ReportMove(NO_IV, before=before, after=after, report_date=rd)
    _, t2 = time_to_expiry(cd, date.fromisoformat(post_exp))
    pct = report_move_pct(s1, s2, t2)
    if pct is None:
        return ReportMove(NOT_SEPARATED, t2_years=t2, before=before, after=after, report_date=rd)
    return ReportMove(OK, pct=pct, e=pct / REPORT_SHARE, t2_years=t2, before=before, after=after, report_date=rd)
