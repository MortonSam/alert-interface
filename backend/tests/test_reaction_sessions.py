"""Reaction windows must land on exchange sessions, not row positions.

Built from the broken EQR history yfinance returned on 2026-09-21: 14 bars for a
five-year request, nothing between 07-22 and 08-06, zero-volume bars from 08-18.
Row-position offsets turned 08-06 into "T+1" and stored -2.3283 / -5.6670 / -3.3973.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.scripts.compute_analyst_reactions import _compute_pre_market
from app.scripts.seed_historical_reactions import _close_at_offset, _compute, _compute_v3

EQR_BARS = [  # (date, open, close, volume) exactly as returned
    (date(2026, 7, 17), 70.24, 69.00, 2313477),
    (date(2026, 7, 20), 69.00, 68.80, 2213705),
    (date(2026, 7, 21), 68.71, 68.29, 2641474),
    (date(2026, 7, 22), 68.61, 68.29, 2868953),
    (date(2026, 8, 6), 67.75, 66.70, 1900745),
    (date(2026, 8, 11), 65.59, 65.09, 2283684),
    (date(2026, 8, 12), 65.04, 64.42, 7042755),
    (date(2026, 8, 13), 65.09, 65.97, 4154364),
    (date(2026, 8, 14), 66.13, 65.97, 7322801),
    (date(2026, 8, 17), 65.96, 63.66, 17443419),
    (date(2026, 8, 18), 63.66, 63.66, 0),
    (date(2026, 8, 19), 63.66, 63.66, 0),
    (date(2026, 8, 20), 63.66, 63.66, 0),
    (date(2026, 8, 21), 63.66, 63.66, 0),
]
EVENT = date(2026, 7, 22)


def _hist(bars):
    df = pd.DataFrame(
        {"Open": [b[1] for b in bars], "Close": [b[2] for b in bars], "Volume": [b[3] for b in bars]},
        index=pd.DatetimeIndex([pd.Timestamp(b[0]) for b in bars]),
    )
    return df, df.index.map(lambda ts: ts.date()).values


def _weekday_sessions(start: date, end: date) -> np.ndarray:
    """Reference calendar: every weekday in range (no holidays fall inside it)."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return np.array(out, dtype=object)


SESSIONS = _weekday_sessions(date(2026, 7, 13), date(2026, 9, 18))


def test_eqr_amc_moves_are_null_not_borrowed_from_later_bars():
    hist, dates = _hist(EQR_BARS)
    out = _compute_v3(hist, dates, EVENT, "amc", SESSIONS)
    assert out is not None
    assert out["pct_change_1d"] is None  # 07-23 missing; old code used 08-06 -> -2.3283
    assert out["pct_change_3d"] is None  # 07-27 missing; old code used 08-12 -> -5.6670
    assert out["pct_change_5d"] is None  # 07-29 missing; old code used 08-14 -> -3.3973


def test_eqr_bmo_has_no_valid_window_either():
    hist, dates = _hist(EQR_BARS)
    # base = close(07-21) = 68.29 and close(07-22) = 68.29: the frozen-price guard
    # nulls 1d, and the 3d/5d sessions (07-24, 07-28) are missing.
    out = _compute_v3(hist, dates, EVENT, "bmo", SESSIONS)
    assert (out["pct_change_1d"], out["pct_change_3d"], out["pct_change_5d"]) == (None, None, None)


def test_bmo_keeps_1d_when_t_and_prior_session_exist_but_later_sessions_do_not():
    hist, dates = _hist(EQR_BARS)
    out = _compute_v3(hist, dates, date(2026, 7, 21), "bmo", SESSIONS)
    assert float(out["pct_change_1d"]) == round((68.29 - 68.80) / 68.80 * 100, 4)
    assert out["pct_change_3d"] is None  # T+2 = 07-23 missing
    assert out["pct_change_5d"] is None  # T+4 = 07-27 missing


def test_event_on_a_session_the_ticker_has_no_bar_for_returns_none():
    hist, dates = _hist(EQR_BARS)
    # 07-23 was a session. Old code rolled T forward to the 08-06 bar.
    assert _compute_v3(hist, dates, date(2026, 7, 23), "amc", SESSIONS) is None
    assert _compute(hist, dates, date(2026, 7, 23), SESSIONS) is None


def test_bmo_base_must_be_the_prior_session():
    hist, dates = _hist(EQR_BARS)
    # T = 08-06 exists, but 08-05 does not: base would have been the 07-22 close.
    assert _compute_v3(hist, dates, date(2026, 8, 6), "bmo", SESSIONS) is None


def test_exact_session_bar_is_used_even_when_an_earlier_session_is_missing():
    hist, dates = _hist(EQR_BARS)
    # T = 08-11. T+1 = 08-12 present, T+3 = 08-14 present, T+2 (08-13) present.
    assert _close_at_offset(hist, dates, SESSIONS, date(2026, 8, 11), 1) == 64.42
    assert _close_at_offset(hist, dates, SESSIONS, date(2026, 8, 11), 3) == 65.97
    # T = 08-06: T+3 = 08-11 is present although 08-07 and 08-10 are missing.
    assert _close_at_offset(hist, dates, SESSIONS, date(2026, 8, 6), 3) == 65.09
    assert _close_at_offset(hist, dates, SESSIONS, date(2026, 8, 6), 1) is None


def test_zero_volume_bar_in_window_nulls_the_move():
    hist, dates = _hist(EQR_BARS)
    t = date(2026, 8, 14)
    assert _close_at_offset(hist, dates, SESSIONS, t, 1) == 63.66      # 08-17 traded
    assert _close_at_offset(hist, dates, SESSIONS, t, 2) is None       # 08-18 zero volume
    assert _close_at_offset(hist, dates, SESSIONS, t, 5) is None       # passes through frozen bars


def test_session_beyond_the_calendar_or_history_is_null():
    hist, dates = _hist(EQR_BARS)
    assert _close_at_offset(hist, dates, SESSIONS, date(2026, 8, 21), 5) is None
    assert _close_at_offset(hist, dates, SESSIONS, date(2026, 7, 18), 1) is None  # Saturday is not a session


def test_fomc_compute_on_broken_history():
    hist, dates = _hist(EQR_BARS)
    out = _compute(hist, dates, date(2026, 7, 20), SESSIONS)
    # T = 07-20 (open 69.00), T+1 = 07-21 present; T+3 (07-23) and T+5 (07-27) missing
    assert float(out["pct_change_1d"]) == round((68.29 - 69.00) / 69.00 * 100, 4)
    assert out["pct_change_3d"] is None and out["pct_change_5d"] is None


def test_complete_history_is_unchanged_by_the_session_check():
    bars = [(d, 100.0 + i, 100.5 + i, 1_000_000) for i, d in enumerate(SESSIONS[:15])]
    hist, dates = _hist(bars)
    t = SESSIONS[3]
    out = _compute_v3(hist, dates, t, "amc", SESSIONS)
    base = 100.5 + 3
    assert float(out["pct_change_1d"]) == round((100.5 + 4 - base) / base * 100, 4)
    assert float(out["pct_change_3d"]) == round((100.5 + 6 - base) / base * 100, 4)
    assert float(out["pct_change_5d"]) == round((100.5 + 8 - base) / base * 100, 4)


def test_analyst_reaction_requires_day0_and_prior_session():
    hist, dates = _hist(EQR_BARS)
    assert _compute_pre_market(hist, dates, date(2026, 7, 23), SESSIONS) is None   # no day-0 bar
    assert _compute_pre_market(hist, dates, date(2026, 8, 6), SESSIONS) is None    # no prior-session bar
    ok = _compute_pre_market(hist, dates, date(2026, 8, 12), SESSIONS)
    assert ok["pct_change_1d"] == round((64.42 - 65.09) / 65.09 * 100, 4)
    # 08-12 + 4 calendar days = 08-16 (Sun) -> 08-17 session, present and traded
    assert ok["pct_change_5d"] == round((63.66 - 65.09) / 65.09 * 100, 4)
