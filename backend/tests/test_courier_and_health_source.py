"""The courier's missed-day warning, health's options date from the primary source, and display names by symbol."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.scripts.validate_data import courier_session_due
from app.services.briefing import short_name
from app.services.dataset_freshness import COURIER_STEP_LABEL, dataset_ages, datasets_for

NY = ZoneInfo("America/New_York")


def test_the_courier_is_due_for_today_only_after_its_window():
    assert courier_session_due(datetime(2026, 10, 9, 16, 30, tzinfo=NY)) == date(2026, 10, 8)    # Friday, still running
    assert courier_session_due(datetime(2026, 10, 9, 17, 0, tzinfo=NY)) == date(2026, 10, 9)     # Friday after the window
    assert courier_session_due(datetime(2026, 10, 10, 4, 30, tzinfo=NY)) == date(2026, 10, 9)    # Saturday's validate
    assert courier_session_due(datetime(2026, 10, 12, 4, 30, tzinfo=NY)) == date(2026, 10, 9)    # Monday morning: Friday's


def test_the_options_dataset_follows_the_primary_source():
    assert datasets_for("intrinio")["chains"] == ("Options chains (Intrinio)",)
    assert datasets_for("courier")["chains"] == (COURIER_STEP_LABEL,)
    outcomes = {"Options chains (Intrinio)": {"exit": 0}, COURIER_STEP_LABEL: {"exit": 0}}
    stamps = {"Options chains (Intrinio)": "2026-10-10T07:48:35+00:00", COURIER_STEP_LABEL: "2026-10-08T20:33:54+00:00"}
    assert dataset_ages(outcomes, stamps, primary="intrinio")["chains"]["at"].startswith("2026-10-10T07:48")
    assert dataset_ages(outcomes, stamps, primary="courier")["chains"]["at"].startswith("2026-10-08T20:33")


def test_display_names_by_symbol():
    assert short_name("American International Group, Inc.", "AIG") == "AIG"
    assert short_name("Public Service Enterprise Group Incorporated", "PEG") == "PSEG"
    assert short_name("The Walt Disney Company", "DIS") == "Disney"
    assert short_name("The Hartford Insurance Group, Inc.", "HIG") == "Hartford"
    assert short_name("The Walt Disney Company") == "Walt Disney"            # without the symbol, the general rule
