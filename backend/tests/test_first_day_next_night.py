"""A report's first-day move is stored the night after its first full session closes, and its 3- and 5-day moves fill in later
on the same row (Sam, 2026-10-29). An empty longer window on a recent report is not yet available, never zero."""
from datetime import date

import pandas as pd

from app.scripts.seed_historical_reactions import FULL_WINDOW_DAYS, MIN_AGE_DAYS, _compute_v3, stored_report_entries, write_now
from app.services.reaction_windows import NOT_YET, WINDOW_FILL_DAYS, pending_windows

OCT28 = date(2026, 10, 28)     # a Wednesday; reported after the close
SESSIONS = [date(2026, 10, d) for d in (26, 27, 28, 29, 30)] + [date(2026, 11, d) for d in (2, 3, 4, 5, 6)]


def hist_through(last: date):
    days = [d for d in SESSIONS if d <= last]
    closes = {date(2026, 10, 28): 100.0, date(2026, 10, 29): 108.0, date(2026, 10, 30): 107.0, date(2026, 11, 2): 109.0,
              date(2026, 11, 3): 110.0, date(2026, 11, 4): 111.0}
    df = pd.DataFrame({"Open": [closes.get(d, 99.0) for d in days], "High": [120.0] * len(days), "Low": [90.0] * len(days),
                       "Close": [closes.get(d, 99.0) for d in days], "Volume": [1_000_000] * len(days)},
                      index=pd.DatetimeIndex([pd.Timestamp(d) for d in days]))
    dates = df.index.map(lambda ts: ts.date()).values
    sessions = pd.Index(days).values
    return df, dates, sessions


def compute(last: date):
    df, dates, sessions = hist_through(last)
    return _compute_v3(df, dates, OCT28, "amc", sessions)


def test_the_night_of_oct_29_nothing_is_written_yet():
    data = compute(date(2026, 10, 28))                      # the 02:30 run on Oct 29: Oct 29's session has not closed
    assert data["pct_change_1d"] is None
    assert not write_now(data, OCT28, date(2026, 10, 29))


def test_after_the_oct_29_close_the_first_day_move_is_stored_and_the_longer_ones_wait():
    data = compute(date(2026, 10, 29))                      # the run on Oct 30
    assert float(data["pct_change_1d"]) == 8.0
    assert data["pct_change_3d"] is None and data["pct_change_5d"] is None
    assert write_now(data, OCT28, date(2026, 10, 30))
    assert pending_windows(OCT28, data["pct_change_1d"], None, None, date(2026, 10, 30)) == ["3d", "5d"]


def test_the_5_day_window_fills_in_later_on_the_same_report():
    mid = compute(date(2026, 11, 2))                        # T+3 closed: the 3-day move arrives, the 5-day still waits
    assert float(mid["pct_change_3d"]) == 9.0 and mid["pct_change_5d"] is None
    full = compute(date(2026, 11, 4))                       # T+5 closed
    assert float(full["pct_change_5d"]) == 11.0
    assert pending_windows(OCT28, full["pct_change_1d"], full["pct_change_3d"], full["pct_change_5d"], date(2026, 11, 5)) == []


def test_a_report_from_yesterday_is_now_a_candidate():
    entries, _ = stored_report_entries([(OCT28, None, None, "amc", True, None)], date(2026, 10, 30))
    assert [e[0] for e in entries] == [OCT28]
    assert MIN_AGE_DAYS == 1


def test_older_reports_keep_their_rule_and_old_gaps_are_not_on_file():
    assert write_now({"pct_change_1d": None}, OCT28, date(2026, 11, 5))     # 8 days: written as always
    assert FULL_WINDOW_DAYS == 8
    assert pending_windows(date(2026, 1, 15), 4.0, None, None, date(2026, 10, 30)) == []            # long past: a gap, not pending
    assert pending_windows(OCT28, None, None, None, date(2026, 10, 30)) == []                       # no first day, nothing pending
    assert WINDOW_FILL_DAYS >= 9 and NOT_YET == "not yet available"
