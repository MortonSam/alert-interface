"""The repair plan: delete what sits off an official day, insert the missing event, seed the day that never ran."""
from datetime import date

from app.scripts.repair_fomc_dates import plan


def test_the_plan_from_the_production_state_of_2026_10_01():
    reaction_days = {date(2025, 12, 17): 508, date(2026, 9, 16): 510, date(2026, 9, 17): 13, date(2026, 7, 29): 509}
    event_days = {date(2025, 12, 17): 1, date(2026, 9, 16): 1, date(2026, 9, 17): 1, date(2026, 10, 28): 1, date(2026, 10, 29): 1,
                  date(2026, 12, 9): 1, date(2026, 12, 16): 1, date(2026, 7, 29): 1}
    with_rows = {date(2026, 9, 16): {"AAPL", "MU"}, date(2026, 7, 29): {"AAPL", "MU"}, date(2025, 12, 17): {"AAPL", "MU"}}
    p = plan(reaction_days, event_days, with_rows, ["AAPL", "MU"], date(2026, 10, 1))
    assert p.delete_reactions == {date(2025, 12, 17): 508, date(2026, 9, 17): 13}
    assert p.delete_events == {date(2025, 12, 17): 1, date(2026, 9, 17): 1, date(2026, 10, 29): 1, date(2026, 12, 16): 1}
    assert date(2025, 12, 10) in p.insert_events and date(2026, 9, 16) not in p.insert_events
    assert date(2025, 12, 10) in p.seed and p.seed[date(2025, 12, 10)] == ["AAPL", "MU"]
    assert date(2026, 9, 16) not in p.seed                       # has its rows
    assert date(2026, 10, 28) not in p.seed                      # future: the nightly seeds it in its own time
    assert not p.empty()


def test_a_clean_table_plans_nothing_and_a_few_stragglers_are_left_to_the_nightly():
    from datetime import timedelta
    from app.scripts.seed_fomc_reactions import LOOKBACK_YEARS, MIN_AGE_DAYS
    from app.services.fomc_calendar import decision_days
    today = date(2026, 10, 1)
    window = decision_days(today - timedelta(days=LOOKBACK_YEARS * 366), today - timedelta(days=MIN_AGE_DAYS))
    reaction_days = {d: 500 for d in window}
    event_days = {d: 1 for d in decision_days()}
    with_rows = {d: {f"T{i}" for i in range(500)} for d in window}
    p = plan(reaction_days, event_days, with_rows, [f"T{i}" for i in range(503)], today)
    assert p.delete_reactions == {} and p.delete_events == {} and p.seed == {} and p.insert_events == []
    assert p.empty()


def test_the_script_is_a_dry_run_unless_told_to_write():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "repair_fomc_dates.py").read_text()
    assert 'write = "--write" in argv' in src and "if write and not p.empty():" in src
    assert src.index("print_plan(p, write)") < src.index("await apply(p)")
