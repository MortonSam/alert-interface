"""The in-house IV: a known case to four decimals, the shared expiry rule, the rate that fails closed, and the two checks."""
import math
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.iv_history import COURIER_SOURCE, SOLVER_SOURCE
from app.scripts import refresh
from app.scripts.solve_atm_iv import STEP_LABEL
from app.scripts.validate_data import CHECKS, ERROR, PASS, WARN, check_iv_solver_band, check_iv_vendor_band, run_checks
from app.services.iv_solver import (DAY_COUNT, DIVIDEND_YIELD, IV_BRACKET_HIGH, IV_BRACKET_LOW, IV_SANITY_MAX, IV_SANITY_MIN, IV_SOLVER_VERSION,
                                    MIN_ATM_MID, MIN_EXPIRY_DAYS, RATE_MAX_AGE_SESSIONS, RATE_SCALE, RATE_SERIES, bs_price, choose_expiration,
                                    implied_vol, mid, nonstandard_mids, solve_atm, time_to_expiry)
from app.services.rates import parse_fred_csv, pick_rate


# ── the solver ────────────────────────────────────────────────────────────────

def test_a_known_case_prices_and_solves_back_to_four_decimals():
    # Hull's textbook case: S=42, K=40, r=10%, sigma=20%, T=0.5: call 4.76, put 0.81
    assert round(bs_price("call", 42, 40, 0.5, 0.10, 0.20), 2) == 4.76
    assert round(bs_price("put", 42, 40, 0.5, 0.10, 0.20), 2) == 0.81
    # at-the-money one-year, r=5%, sigma=20%: call 10.4506, put 5.5735
    c, p = bs_price("call", 100, 100, 1.0, 0.05, 0.20), bs_price("put", 100, 100, 1.0, 0.05, 0.20)
    assert round(c, 4) == 10.4506 and round(p, 4) == 5.5735
    assert round(implied_vol("call", c, 100, 100, 1.0, 0.05).iv, 4) == 0.2000
    assert round(implied_vol("put", p, 100, 100, 1.0, 0.05).iv, 4) == 0.2000
    # put-call parity holds, so both sides of one fair pair solve to the same sigma
    call_px, parity_put = 3.2, 3.2 - (1097.39 - 1100 * math.exp(-0.04 * 8 / 365))
    assert abs(implied_vol("call", call_px, 1097.39, 1100, 8 / 365, 0.04).iv - implied_vol("put", parity_put, 1097.39, 1100, 8 / 365, 0.04).iv) < 1e-6


def test_the_assumptions_are_the_stated_constants():
    assert IV_SOLVER_VERSION == 1 and DAY_COUNT == 365 and DIVIDEND_YIELD == 0.0
    assert RATE_SERIES == "DTB3" and RATE_SCALE == 0.01 and RATE_MAX_AGE_SESSIONS == 5
    assert IV_BRACKET_LOW < IV_SANITY_MIN == 0.02 and IV_SANITY_MAX == 5.0 < IV_BRACKET_HIGH
    assert MIN_EXPIRY_DAYS == 7
    assert time_to_expiry(date(2026, 10, 1), date(2026, 10, 9)) == (8, 8 / 365)


def test_the_mid_needs_both_sides_quoted_and_the_solver_says_why_it_cannot_solve():
    assert mid(5.0, 5.4) == 5.2
    assert mid(0, 5.4) is None and mid(5.0, None) is None and mid(5.4, 5.0) is None
    assert implied_vol("call", None, 100, 100, 0.1, 0.04).reason.startswith("no mid")
    assert "no-volatility price" in implied_vol("call", 0.5, 100, 90, 0.1, 0.04).reason      # below intrinsic
    assert "at or above the price at" in implied_vol("call", 99.0, 100, 100, 0.1, 0.04).reason
    assert implied_vol("call", 5.0, 100, 100, 0.0, 0.04).reason.startswith("expiry is not after")


def test_the_expiry_rule_matches_snapshot_iv_nearest_at_least_seven_days_out_else_the_farthest():
    exps = ["2026-10-02", "2026-10-09", "2026-10-16", "2027-01-15"]
    assert choose_expiration(exps, date(2026, 10, 1)) == "2026-10-09"       # 2026-10-08 floor: the 2nd is one day short
    assert choose_expiration(exps, date(2026, 10, 2)) == "2026-10-09"
    assert choose_expiration(exps, date(2026, 10, 3)) == "2026-10-16"
    assert choose_expiration(["2026-10-02", "2026-10-03"], date(2026, 10, 1)) == "2026-10-03"   # nothing far enough: the farthest
    assert choose_expiration([], date(2026, 10, 1)) is None


def test_solve_atm_takes_the_strike_quoted_on_both_sides_nearest_the_spot_and_keeps_the_vendor_ivs():
    chain = {"calls": [{"strike": 1090, "bid": 40, "ask": 41, "impliedVolatility": 0.55}, {"strike": 1095, "bid": 35.25, "ask": 37.0, "impliedVolatility": 0.57027}],
             "puts": [{"strike": 1095, "bid": 31.75, "ask": 34.5, "impliedVolatility": 0.50229}, {"strike": 1100, "bid": 36, "ask": 37, "impliedVolatility": 0.5}]}
    a = solve_atm(chain, 1097.39, date(2026, 10, 1), date(2026, 10, 9), 0.04)
    assert a.strike == 1095.0 and a.call_mid == 36.125 and a.put_mid == 33.125 and a.days == 8
    assert a.call.iv is not None and a.put.iv is not None and a.atm_iv == (a.call.iv + a.put.iv) / 2
    assert a.vendor_call_iv == 0.57027 and a.vendor_put_iv == 0.50229 and round(a.vendor_iv, 5) == 0.53628
    assert bs_price("call", 1097.39, 1095, 8 / 365, 0.04, a.call.iv) == pytest.approx(36.125, abs=1e-6)
    half = solve_atm({"calls": chain["calls"], "puts": [{"strike": 1095, "bid": 0, "ask": 34.5}]}, 1097.39, date(2026, 10, 1), date(2026, 10, 9), 0.04)
    assert half.put.iv is None and half.atm_iv == half.call.iv and half.reason.startswith("put: no mid")


def test_a_penny_atm_mid_marks_the_chain_nonstandard_and_the_step_writes_no_row_for_it():
    """WBD on 2026-10-02: spot 30.94, strike 31, call mid 0.015, put mid 0.045: a separated deliverable, not a 1.5% vol."""
    assert MIN_ATM_MID == 0.05
    assert nonstandard_mids(0.015, 0.045) and nonstandard_mids(1.20, 0.04) and nonstandard_mids(None, 0.01)
    assert not nonstandard_mids(0.05, 0.05) and not nonstandard_mids(36.125, 33.125) and not nonstandard_mids(None, None)
    wbd = {"calls": [{"strike": 31, "bid": 0.01, "ask": 0.02, "impliedVolatility": 0.0164}], "puts": [{"strike": 31, "bid": 0.04, "ask": 0.05, "impliedVolatility": 0.0164}]}
    a = solve_atm(wbd, 30.94, date(2026, 10, 2), date(2026, 10, 9), 0.04)
    assert (a.call_mid, a.put_mid) == (0.015, 0.045) and nonstandard_mids(a.call_mid, a.put_mid)
    # the step's branch: what the outcome records and that no row is planned
    import inspect
    from app.scripts import solve_atm_iv
    src = inspect.getsource(solve_atm_iv.run)
    assert "if nonstandard_mids(a.call_mid, a.put_mid):" in src and "skipped_nonstandard[sym]" in src
    branch = src.split("if nonstandard_mids(a.call_mid, a.put_mid):")[1].split("continue")[0]
    assert all(k in branch for k in ('"spot"', '"strike"', '"call_mid"', '"put_mid"', "DELETE FROM iv_history"))   # recorded, stale row removed, then continue


# ── the rate ──────────────────────────────────────────────────────────────────

def test_the_rate_is_the_latest_published_value_within_five_sessions_else_none_with_a_reason():
    rows = [(date(2026, 9, 29), 4.07), (date(2026, 9, 30), 4.03), (date(2026, 10, 1), 4.00)]
    assert pick_rate(rows, date(2026, 10, 1)) .rate == pytest.approx(0.0400)
    r = pick_rate(rows, date(2026, 10, 7))                 # 10-01 is 3 sessions before 10-07: still good
    assert r.rate == pytest.approx(0.04) and r.rate_date == date(2026, 10, 1)
    r = pick_rate(rows, date(2026, 10, 12))                # 6 sessions (Oct 2, 5, 6, 7, 8, 9): fail closed
    assert r.rate is None and "6 sessions before 2026-10-12" in r.reason and "limit 5" in r.reason
    r = pick_rate(rows, date(2026, 9, 1))
    assert r.rate is None and "on or before 2026-09-01" in r.reason
    assert pick_rate([], date(2026, 10, 1)).rate is None


def test_fred_csv_parses_dates_and_skips_missing_observations():
    body = "observation_date,DTB3\n2026-09-29,4.07\n2026-09-30,.\n2026-10-01,4.00\n"
    assert parse_fred_csv(body) == [(date(2026, 9, 29), 4.07), (date(2026, 10, 1), 4.00)]


# ── wiring and readers ────────────────────────────────────────────────────────

def test_the_step_follows_the_intrinio_chains_step_and_the_checks_are_registered():
    labels = [label for label, _ in refresh.STEPS]
    assert labels.index("Options chains (Intrinio)") < labels.index(STEP_LABEL) < labels.index("Validate data")
    assert check_iv_vendor_band in CHECKS and check_iv_solver_band in CHECKS


def test_every_iv_history_reader_filters_to_courier_rows():
    """The solver's rows sit beside the courier's in iv_history; nothing serves them. Every query of the table outside the
    solver's own writer and checks names the courier source."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app"
    exempt = {"scripts/solve_atm_iv.py", "scripts/iv_cleanup.py"}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        src = path.read_text()
        queries = "FROM iv_history" in src or "from iv_history" in src or "select(IVHistory" in src or "UPDATE iv_history" in src
        if rel in exempt or not queries or rel.startswith("models/"):
            continue
        if rel == "scripts/validate_data.py":
            # every SQL block that reads iv_history names a source
            blocks = [b for b in re.split(r'text\("""', src) if "iv_history" in b.split('"""')[0]]
            for b in blocks:
                sql = b.split('"""')[0]
                assert "iv_source" in sql, f"validate_data: an iv_history query without iv_source: {sql[:120]}"
            continue
        assert "iv_source" in src or "COURIER_SOURCE" in src, f"{rel} reads iv_history without naming the courier source"


# ── the checks, against the database ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_vendor_band_counts_gaps_and_the_solver_band_errors_outside_it():
    syms = [f"ZZIV{i}" for i in range(4)]
    d = date(2099, 1, 2)            # a night no real row reaches, so it is the latest
    try:
        async with ScriptSessionLocal() as s:
            for sym, atm, vend, call in ((syms[0], 0.50, 0.52, 0.51), (syms[1], 0.50, 0.70, 0.49), (syms[2], 0.80, None, 0.80), (syms[3], 0.50, 0.49, 0.50)):
                await s.execute(text("""INSERT INTO iv_history (id, symbol, date, iv_source, iv_version, atm_iv, vendor_iv, solved_call_iv, solved_put_iv, current_price, atm_strike, rate, days_to_expiry)
                                        VALUES (gen_random_uuid(), :s, :d, :src, 1, :atm, :vend, :call, :atm, 100, 100, 0.04, 8)"""),
                                {"s": sym, "d": d, "src": SOLVER_SOURCE, "atm": atm, "vend": vend, "call": call})
            await s.commit()
        vendor, band = await run_checks([check_iv_vendor_band, check_iv_solver_band])
        assert vendor.level == WARN and vendor.message.startswith("1/3 ticker(s) (33.3%) differ")          # ZZIV1 gaps; ZZIV2 has no vendor IV
        assert vendor.rows[0].startswith("4 solver row(s) on 2099-01-02, 3 with both IVs, 1 without")
        assert vendor.rows[1].startswith(f"{syms[1]}: solved 0.5000") and "gap 0.2000" in vendor.rows[1] and "mids None/None, spot 100" in vendor.rows[1]
        assert not any(sym in r for sym in syms for r in band.rows)      # the synthetic rows are inside the band (other rows may not be)
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE iv_history SET solved_put_iv = 6.5 WHERE symbol = :s AND date = :d"), {"s": syms[3], "d": d})
            await s.commit()
        band = (await run_checks([check_iv_solver_band]))[0]
        assert band.level == ERROR and any(syms[3] in r and "put 6.5" in r for r in band.rows)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM iv_history WHERE symbol = ANY(:s)"), {"s": syms})
            await s.commit()


@pytest.mark.asyncio
async def test_a_courier_row_and_a_solver_row_share_a_symbol_and_date_and_the_served_reader_sees_only_the_courier():
    from app.services.iv_store import get_servable_iv
    sym, d = "ZZIVS", date.today()
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO iv_history (id, symbol, date, iv_source, atm_iv) VALUES (gen_random_uuid(), :s, :d, :c, 0.30)"), {"s": sym, "d": d, "c": COURIER_SOURCE})
            await s.execute(text("INSERT INTO iv_history (id, symbol, date, iv_source, iv_version, atm_iv) VALUES (gen_random_uuid(), :s, :d, :v, 1, 0.90)"), {"s": sym, "d": d, "v": SOLVER_SOURCE})
            await s.commit()
        async with ScriptSessionLocal() as s:
            state = await get_servable_iv(s, sym, d)
        assert state.value == 0.30 and state.as_of == d.isoformat()
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM iv_history WHERE symbol = :s"), {"s": sym})
            await s.commit()
