"""Stored EPS actuals are matched to EDGAR XBRL quarters; Q4 is derived when only the FY is filed."""
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.eps_basis import Fact, match_actual, quarter_facts

D = Decimal


def _facts(entries, tag="EarningsPerShareDiluted", basic=None):
    us = {tag: {"units": {"USD/shares": entries}}}
    if basic is not None:
        us["EarningsPerShareBasic"] = {"units": {"USD/shares": basic}}
    return {"facts": {"us-gaap": us}}


UBER = [
    {"start": "2024-01-01", "end": "2024-09-30", "val": 1.36, "filed": "2024-10-31"},   # 9-month, ignored
    {"start": "2024-07-01", "end": "2024-09-30", "val": 1.2, "filed": "2024-10-31"},
    {"start": "2024-01-01", "end": "2024-12-31", "val": 4.56, "filed": "2025-02-14"},   # FY
    {"start": "2024-10-01", "end": "2024-12-31", "val": 3.21, "filed": "2026-01-12"},   # standalone Q4 from an 8-K
    {"start": "2025-01-01", "end": "2025-03-31", "val": 0.83, "filed": "2025-05-07"},
]


def test_quarter_facts_keeps_quarters_and_every_reported_value():
    q = quarter_facts(_facts(UBER))
    assert sorted(q) == [date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31)]
    assert q[date(2024, 12, 31)][0].value == 3.21 and q[date(2024, 12, 31)][0].tag == "EarningsPerShareDiluted"


def test_q4_is_derived_from_fy_when_no_standalone_value():
    entries = [
        {"start": "2024-01-01", "end": "2024-03-31", "val": 1.00, "filed": "2024-05-01"},
        {"start": "2024-04-01", "end": "2024-06-30", "val": 1.10, "filed": "2024-08-01"},
        {"start": "2024-07-01", "end": "2024-09-30", "val": 1.20, "filed": "2024-11-01"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 4.50, "filed": "2025-02-14"},
    ]
    q = quarter_facts(_facts(entries))
    q4 = q[date(2024, 12, 31)]
    assert len(q4) == 1 and q4[0].value == 1.2 and q4[0].tag == "derived_q4:EarningsPerShareDiluted"


def test_basic_only_fills_quarters_diluted_lacks():
    diluted = [{"start": "2024-01-01", "end": "2024-03-31", "val": 1.00, "filed": "2024-05-01"}]
    basic = [{"start": "2024-01-01", "end": "2024-03-31", "val": 1.02, "filed": "2024-05-01"},
             {"start": "2024-04-01", "end": "2024-06-30", "val": 1.12, "filed": "2024-08-01"}]
    q = quarter_facts(_facts(diluted, basic=basic))
    assert q[date(2024, 3, 31)][0].value == 1.00
    assert q[date(2024, 6, 30)][0].tag == "EarningsPerShareBasic"


def test_match_statuses():
    q = quarter_facts(_facts(UBER))
    # UBER 2025-02-05: stored 3.21 = XBRL Q4 3.21 -> GAAP
    m = match_actual(D("3.21"), date(2025, 2, 5), q, [])
    assert m.status == "matched" and m.period_end == date(2024, 12, 31) and m.xbrl_eps == 3.21
    # an adjusted figure does not match
    m = match_actual(D("0.48"), date(2025, 2, 5), q, [])
    assert m.status == "unmatched" and m.xbrl_eps == 3.21
    # stored actual on the post-split basis while XBRL is pre-split: 1.2 / 2 = 0.60
    m = match_actual(D("0.60"), date(2024, 10, 31), q, [(2.0, date(2025, 6, 1))])
    assert m.status == "off_by_split" and m.split_factor == 2.0
    # no quarter ends within 120 days before the event
    assert match_actual(D("1.0"), date(2025, 9, 1), q, []).status == "no_fact"
    # nearest period end before the event, not the nearest overall
    assert match_actual(D("1.2"), date(2024, 12, 15), q, []).period_end == date(2024, 9, 30)


def test_restated_value_for_the_same_period_can_match():
    facts = {date(2024, 3, 31): [Fact(date(2024, 3, 31), 2.00, "EarningsPerShareDiluted", "2024-05-01"),
                                 Fact(date(2024, 3, 31), 1.00, "EarningsPerShareDiluted", "2025-05-01")]}  # restated post-split
    assert match_actual(D("1.00"), date(2024, 4, 25), facts, []).status == "matched"


def test_script_caches_companyfacts_per_cik_and_writes_only_the_checks_table():
    src = Path(__file__).resolve().parents[1].joinpath("app/scripts/check_eps_basis.py").read_text()
    assert 'companyfacts_{cik}.json' in src and "_cache_fresh(" in src
    assert "pg_insert(EpsBasisCheck)" in src
    assert "UPDATE historical_reactions" not in src and "outcome" not in src.replace("outcome ", "")
