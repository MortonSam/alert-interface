"""FOMC decision days come from one module, match the Fed's page, and every FOMC row sits on one of them."""
from datetime import date

from app.services.fomc_calendar import (
    DECISION_DAYS, decision_days, disagreements, is_decision_day, next_year_covered, parse_fed_calendar,
)

FED_HTML = """
<div class="panel panel-default"><div class="panel-heading"><h4><a id="39116">2024 FOMC Meetings</a></h4></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>January</strong></div><div class="fomc-meeting__date">30-31</div></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>March</strong></div><div class="fomc-meeting__date">19-20*</div></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>Apr/May</strong></div><div class="fomc-meeting__date">30-1</div></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>December</strong></div><div class="fomc-meeting__date">17-18*</div></div>
</div>
<div class="panel panel-default"><div class="panel-heading"><h4><a id="42827">2025 FOMC Meetings</a></h4></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>August</strong></div><div class="fomc-meeting__date">22 (notation vote)</div></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>October</strong></div><div class="fomc-meeting__date">28-29</div></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>December</strong></div><div class="fomc-meeting__date">9-10*</div></div>
</div>
<div class="panel panel-default"><div class="panel-heading"><h4><a id="36495">2023 FOMC Meetings</a></h4></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>Jan/Feb</strong></div><div class="fomc-meeting__date">31-1</div></div>
 <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>Oct/Nov</strong></div><div class="fomc-meeting__date">31-1</div></div>
</div>
"""


def test_the_module_holds_the_official_days_and_none_of_the_four_wrong_ones():
    assert sorted(DECISION_DAYS) == [2021, 2022, 2023, 2024, 2025, 2026, 2027]
    assert all(len(days) == 8 for days in DECISION_DAYS.values())
    assert DECISION_DAYS[2026] == [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
                                   date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]
    for wrong in (date(2025, 12, 17), date(2026, 9, 17), date(2026, 10, 29), date(2026, 12, 16)):
        assert not is_decision_day(wrong), wrong
    for right in (date(2025, 12, 10), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9), date(2023, 2, 1), date(2024, 5, 1)):
        assert is_decision_day(right), right
    assert decision_days(date(2026, 9, 1), date(2026, 12, 31)) == [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]
    assert next_year_covered(date(2026, 10, 1)) and not next_year_covered(date(2027, 10, 1))


def test_the_fed_page_parser_takes_the_last_day_crosses_months_and_skips_a_notation_vote():
    page = parse_fed_calendar(FED_HTML)
    assert page[2024] == [date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 12, 18)]
    assert page[2025] == [date(2025, 10, 29), date(2025, 12, 10)]
    assert page[2023] == [date(2023, 2, 1), date(2023, 11, 1)]


def test_disagreements_name_each_side_within_the_horizon_only():
    page = {2026: [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
                   date(2026, 7, 29), date(2026, 9, 17), date(2026, 10, 28), date(2026, 12, 9)],     # Sep 17 wrong
            2027: DECISION_DAYS[2027]}
    diffs = disagreements(page, date(2026, 10, 1))
    assert diffs == ["2026-09-17: on the Fed page, not in fomc_calendar.py", "2026-09-16: in fomc_calendar.py, not on the Fed page"]
    # a page that drops a day beyond the 12-month horizon (Oct 27 and Dec 8, 2027 from Oct 1, 2026) is not a disagreement yet
    assert disagreements({2026: DECISION_DAYS[2026], 2027: DECISION_DAYS[2027][:6]}, date(2026, 10, 1)) == []
    assert disagreements({2026: DECISION_DAYS[2026], 2027: DECISION_DAYS[2027][:6]}, date(2026, 11, 1)) == ["2027-10-27: in fomc_calendar.py, not on the Fed page"]
    assert disagreements({2028: [date(2028, 1, 26)]}, date(2027, 6, 1)) == ["2028: on the Fed page, no dates in fomc_calendar.py"]


def test_the_seeder_and_the_macro_script_have_no_fomc_dates_of_their_own():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app"
    seeder = (root / "scripts" / "seed_fomc_reactions.py").read_text()
    assert "FOMC_DECISION_DATES" not in seeder and "date(2026" not in seeder
    assert "ensure_fomc_events(session)" in seeder and "if is_decision_day(r.event_date)" in seeder
    macro = (root / "scripts" / "seed_macro.py").read_text()
    code = "\n".join(l for l in macro.split("\n") if not l.lstrip().startswith(("#", '"""')))
    assert "FOMC_URL" not in code and "fetch_fomc" not in code and "fomc-meeting" not in code and 'MacroEvent(d, "FOMC Meeting"' not in code
    validate = (root / "scripts" / "validate_data.py").read_text()
    for name in ("check_fomc_dates_official", "check_fomc_events_unique", "check_fomc_calendar_matches_fed"):
        assert f"    {name},\n" in validate, name
    # only the calendar module writes the event rows
    for path in root.rglob("*.py"):
        src = path.read_text()
        if 'title="FOMC Meeting"' in src or "title=FOMC_EVENT_TITLE" in src:
            assert path.name == "fomc_calendar.py", path
