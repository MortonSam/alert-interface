"""Which expiries the Intrinio chain step stores (services/chain_shadow.wanted_expirations): the expected move uses the
nearest expiry that captures the report, and the last one that does not isolates the earnings move. An expiry on the report
day counts only for a before-open report; after-close and unknown timing need a later expiry."""
from app.services.chain_shadow import EARNINGS_WINDOW_DAYS, counts_for_report, earnings_expirations, wanted_expirations

CMG_LISTED = ["2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30", "2026-11-06", "2026-11-13", "2026-11-20", "2026-11-27",
              "2026-12-18", "2027-01-15"]
CMG_COURIER = ["2026-10-09", "2026-10-16", "2026-10-23", "2026-11-13", "2026-11-20", "2026-12-18"]


def test_cmg_reporting_oct_28_after_the_close_gets_oct_30_and_the_oct_23_leg():
    assert earnings_expirations(CMG_LISTED, "2026-10-08", [("2026-10-28", "amc")]) == ["2026-10-23", "2026-10-30"]
    got = wanted_expirations(CMG_LISTED, "2026-10-08", CMG_COURIER, [("2026-10-28", "amc")], 5)
    assert got == ["2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30", "2026-11-13"]


def test_an_expiry_on_the_report_day_counts_only_before_the_open():
    assert counts_for_report("2026-10-30", "2026-10-30", "bmo")
    assert not counts_for_report("2026-10-30", "2026-10-30", "amc")
    assert not counts_for_report("2026-10-30", "2026-10-30", None)                  # unknown timing: after the close
    assert counts_for_report("2026-10-31", "2026-10-30", None)
    assert earnings_expirations(CMG_LISTED, "2026-10-08", [("2026-10-30", "bmo")]) == ["2026-10-23", "2026-10-30"]
    assert earnings_expirations(CMG_LISTED, "2026-10-08", [("2026-10-30", "amc")]) == ["2026-10-30", "2026-11-06"]
    assert earnings_expirations(CMG_LISTED, "2026-10-08", [("2026-10-30", None)]) == ["2026-10-30", "2026-11-06"]
    assert earnings_expirations(CMG_LISTED, "2026-10-08", [("2026-10-09", "bmo")]) == ["2026-10-09"]       # nothing listed before it
    assert earnings_expirations(["2026-10-16"], "2026-10-08", [("2026-11-07", "amc")]) == ["2026-10-16"]   # nothing after: the leg alone


def test_the_cap_never_drops_the_front_or_an_earnings_expiry():
    monthly = ["2026-10-16", "2026-11-20", "2026-12-18"]
    got = wanted_expirations(monthly + ["2027-01-15"], "2026-10-08", monthly, [("2026-10-20", "bmo"), ("2026-11-25", "amc")], 2)
    assert got == ["2026-10-16", "2026-11-20", "2026-12-18"]
    assert wanted_expirations(CMG_LISTED, "2026-10-08", [], [], 5) == ["2026-10-09"]       # no courier, no earnings: the front only
    assert EARNINGS_WINDOW_DAYS == 45
