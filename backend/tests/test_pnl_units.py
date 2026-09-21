"""Every option P&L percentage is a percent (-35.0), computed in one place."""
import re
from pathlib import Path

from app.services.pnl_math import (
    compute_option_pnl_at_expiry,
    compute_spread_pnl_from_mids,
    pnl_percent,
)

APP = Path(__file__).resolve().parents[1] / "app"
WRITERS = [
    "services/pnl_math.py",
    "scripts/close_alert_picks.py",
    "routers/thesis.py",
    "routers/discover.py",
]


def test_pnl_percent_is_a_percent():
    assert pnl_percent(-0.70, 2.00) == -35.0
    assert pnl_percent(1.00, 2.00) == 50.0
    assert pnl_percent(-2.00, 2.00) == -100.0
    assert pnl_percent(1.0, 0) is None and pnl_percent(1.0, None) is None


def test_all_writers_agree_on_one_trade():
    # A $2.00 debit call spread (100/105) worth $1.30: a 35% loss, however it is measured.
    cost, value = 2.00, 1.30
    at_expiry = compute_option_pnl_at_expiry(close=101.30, strike=100, spread_strike=105, cost=cost, direction="bullish")
    single_leg = compute_spread_pnl_from_mids(value, None, cost, None, contracts=1)
    spread = compute_spread_pnl_from_mids(3.30, 2.00, 4.00, 2.00, contracts=1)   # net 1.30 vs net 2.00
    nightly_close = pnl_percent(value - cost, cost)                              # close_alert_picks spread-mid path
    assert at_expiry == (-70.0, -35.0)
    assert single_leg == (-70.0, -35.0)
    assert spread == (-70.0, -35.0)
    assert nightly_close == -35.0


def test_contracts_scale_dollars_but_not_percent():
    assert compute_spread_pnl_from_mids(1.30, None, 2.00, None, contracts=3) == (-210.0, -35.0)


def test_total_loss_and_condor_return_on_risk():
    assert compute_option_pnl_at_expiry(90, 100, 105, 2.0, "bullish") == (-200.0, -100.0)
    assert pnl_percent(200.0, 2.50 * 100) == 80.0       # condor: +$200 on $250 at risk
    assert pnl_percent(-300.0, 4.00 * 100) == -75.0


def test_no_writer_computes_a_pnl_percentage_outside_the_helper():
    """A hand-rolled `(x - cost) / cost` next to a pnl name is how the unit split happened."""
    offenders = []
    pattern = re.compile(r"pnl_p\w*\s*=\s*(?!pnl_percent|None|mark\.|float|r\.|_compute)[^\n]*/", re.I)
    for rel in WRITERS:
        src = (APP / rel).read_text()
        body = src.split("def pnl_percent", 1)
        scan = body[0] + body[1].split("\n\n\n", 1)[1] if len(body) == 2 else src
        for m in pattern.finditer(scan):
            offenders.append(f"{rel}: {m.group(0).strip()}")
    assert offenders == []


def test_migration_condition_converts_fractions_and_leaves_percents():
    """Mirror of the SQL predicate in p2q3r4s5t6u7."""
    tol = 0.06

    def is_fraction(stored: float, dollars: float, basis: float) -> bool:
        implied = dollars / basis
        return abs(stored * 100 - implied) < tol and abs(stored - implied) >= tol

    assert is_fraction(-0.35, -70.0, 2.00)          # nightly spread-mid close, stored as a fraction
    assert is_fraction(-1.0, -295.0, 2.95)          # total loss stored as -1.0
    assert not is_fraction(-35.0, -70.0, 2.00)      # already a percent
    assert not is_fraction(-100.0, -295.0, 2.95)    # expiry close, already a percent (DECK locally)
    assert not is_fraction(0.0, 0.0, 2.00)          # zero is the same in both units
