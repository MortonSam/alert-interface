"""The question strip: each catalog condition and its omission, the minimum-sample rule, no literal numbers in templates,
no plumbing words in visible text, receipts present, and the route."""
import re
from datetime import date

import pytest

from app.services import questions as Q

T = date(2026, 10, 6)
NUM = re.compile(r"(?<![\d:])\d+(?:,\d{3})*(?:\.\d+)?(?![\d:])")
PLUMBING = re.compile(r"stored|yfinance|finnhub|rv_rank|quarters|the street|out of 100|_", re.I)


def numbers(text):
    return set(NUM.findall(text))


def receipts(q):
    from app.services.briefing import fmt_date
    dated = [fmt_date(date.fromisoformat(i["as_of"])) for i in q["inputs"] if i["as_of"] and len(i["as_of"]) == 10 and i["as_of"][4] == "-"]
    return " ".join(i["value"] for i in q["inputs"]) + " " + " ".join(dated) + " " + q["rule"]


def assert_clean(q):
    assert q["inputs"] and q["as_of"] and q["rule"]
    assert date.fromisoformat(q["as_of"]) <= date.today() and q.get("as_of_kind") in ("observed", "estimated", "declared")   # an as-of is never ahead
    missing = [n for n in numbers(q["data"]) if n not in receipts(q)]
    assert not missing, (missing, q["data"])
    for t in (q["question"], q["data"], q["idea"]):
        assert not PLUMBING.search(t), t
    assert q["data"].count(". ") <= 1 and q["idea"].count(". ") <= 1          # at most three short sentences in all
    assert not numbers(q["idea"]) - {"1", "20"}                                 # the idea is words; "1-day" and "20-day" name windows


def test_1_reaction_normal_needs_eight_past_reports():
    q = Q.q_reaction_normal(name="Micron Technology", symbol="MU", event_date=date(2026, 9, 30), timing="amc", move_pct=3.0, typical_abs=7.0, larger_count=15, n_reports=20, sample_as_of=date(2026, 6, 25))
    assert q["question"] == "Was Micron Technology's move after this report normal?"
    assert q["data"] == "MU moved +3.0% the next session after its Sep 30, 2026 report, against a typical ±7.0% over the last 20 reports; 15 of those reports moved it more."
    assert "next morning" in q["idea"]
    assert_clean(q)
    assert Q.q_reaction_normal(name="X", symbol="X", event_date=T, timing="bmo", move_pct=1.0, typical_abs=2.0, larger_count=3, n_reports=Q.MIN_REPORTS - 1, sample_as_of=T) is None


def test_2_implied_big_words_the_comparison_and_needs_eight_reports():
    q = Q.q_implied_big(name="Constellation Brands", symbol="STZ", implied_pct=0.06, chain_date=date(2026, 10, 5), next_date=date(2026, 10, 6), typical_abs=4.0, n_reports=20, sample_as_of=date(2026, 7, 1))
    assert q["question"] == "Is a ±6.0% expected move big for Constellation Brands?"
    assert q["data"].endswith("so the market is pricing more than usual.")
    assert_clean(q)
    assert Q.q_implied_big(name="X", symbol="X", implied_pct=0.04, chain_date=T, next_date=T, typical_abs=4.0, n_reports=12, sample_as_of=T)["data"].endswith("about its usual.")
    assert Q.q_implied_big(name="X", symbol="X", implied_pct=0.02, chain_date=T, next_date=T, typical_abs=4.0, n_reports=12, sample_as_of=T)["data"].endswith("less than usual.")
    assert Q.q_implied_big(name="X", symbol="X", implied_pct=0.06, chain_date=T, next_date=T, typical_abs=4.0, n_reports=7, sample_as_of=T) is None


def test_3_beat_fell_needs_half_of_at_least_eight_beats():
    q = Q.q_beat_fell(name="Micron Technology", symbol="MU", beats=18, fell=11, as_of=date(2026, 6, 25))
    assert q["data"] == "MU fell the next session after 11 of its last 18 beats (61%)."
    assert_clean(q)
    assert Q.q_beat_fell(name="X", symbol="X", beats=16, fell=8, as_of=T)                    # exactly 50% asks
    assert Q.q_beat_fell(name="X", symbol="X", beats=16, fell=7, as_of=T) is None             # under it does not
    assert Q.q_beat_fell(name="X", symbol="X", beats=7, fell=7, as_of=T) is None              # too few beats


def test_4_big_move_ranks_against_five_years_states_no_cause_and_needs_four_times_typical():
    q = Q.q_big_move(name="Fair Isaac", symbol="FICO", move_date=date(2026, 9, 29), move_pct=-26.5, typical_abs=1.6, multiple=16.6, smaller_share=99.84, n_sessions=1254)
    assert q["question"] == "How unusual was Fair Isaac's move on Sep 29, 2026?"
    assert q["data"] == "On Sep 29, 2026 FICO moved -26.5%, about 17 times a typical day for it and larger than 99.8% of its daily moves over the past 5 years (1,254 sessions)."
    assert not re.search(r"because|news|announc|report|cause", q["data"] + q["idea"].replace("Realized volatility measures", ""))
    assert_clean(q)
    assert Q.q_big_move(name="X", symbol="X", move_date=T, move_pct=5.0, typical_abs=1.6, multiple=3.1, smaller_share=90.0, n_sessions=1254) is None
    assert Q.q_big_move(name="X", symbol="X", move_date=T, move_pct=9.0, typical_abs=1.6, multiple=5.6, smaller_share=90.0, n_sessions=Q.MIN_SESSIONS - 1) is None


def test_5_upgrades_needs_a_recent_upgrade_and_eight_sessions_and_words_follow_through_as_direction_kept():
    q = Q.q_upgrades(name="Micron Technology", symbol="MU", upgrades_30d=1, upgrade_sessions=17, median_1d=1.8483, continuation_pct=70.6, sample_5d=17, stats_as_of=date(2026, 10, 6), newest_upgrade=date(2026, 9, 30))
    assert q["data"] == "On its 17 past upgrade days MU's median move was +1.8%, and in 71% of them the five-session move kept the first day's direction."
    assert_clean(q)
    assert Q.q_upgrades(name="X", symbol="X", upgrades_30d=0, upgrade_sessions=17, median_1d=1.0, continuation_pct=70.0, sample_5d=17, stats_as_of=T, newest_upgrade=None) is None
    assert Q.q_upgrades(name="X", symbol="X", upgrades_30d=2, upgrade_sessions=7, median_1d=1.0, continuation_pct=70.0, sample_5d=7, stats_as_of=T, newest_upgrade=T) is None
    thin = Q.q_upgrades(name="X", symbol="X", upgrades_30d=1, upgrade_sessions=9, median_1d=1.0, continuation_pct=70.0, sample_5d=5, stats_as_of=T, newest_upgrade=T)
    assert thin["data"].endswith("median move was +1.0%.")                                    # too few five-session moves: the clause is left out


def test_6_ex_dividend_within_fourteen_days_is_dated_by_when_we_knew_not_by_the_ex_date():
    q = Q.q_ex_dividend(name="Micron Technology", symbol="MU", ex_date=date(2026, 10, 14), amount=0.6, today=T, stored_on=date(2026, 10, 6))
    assert q["data"] == "MU goes ex-dividend on Oct 14, 2026 with a $0.60 per-share dividend."
    assert q["as_of"] == "2026-10-06" and q["as_of_kind"] == "estimated"                       # the refresh that stored it, not the event
    assert_clean(q)
    declared = Q.q_ex_dividend(name="Micron Technology", symbol="MU", ex_date=date(2026, 10, 14), amount=0.15, today=T, stored_on=date(2026, 10, 6), declared_on=date(2026, 9, 30))
    assert declared["as_of"] == "2026-09-30" and declared["as_of_kind"] == "declared"
    assert Q.q_ex_dividend(name="X", symbol="X", ex_date=T + __import__("datetime").timedelta(days=15), amount=1.0, today=T) is None
    assert Q.q_ex_dividend(name="X", symbol="X", ex_date=T - __import__("datetime").timedelta(days=1), amount=1.0, today=T) is None
    assert Q.q_ex_dividend(name="X", symbol="X", ex_date=T, amount=None, today=T)["data"] == "X goes ex-dividend on Oct 6, 2026."


def test_6_ex_dividend_says_per_share_and_the_amount_is_a_payment():
    q = Q.q_ex_dividend(name="Micron Technology", symbol="MU", ex_date=date(2026, 10, 14), amount=0.15, today=T)
    assert q["data"] == "MU goes ex-dividend on Oct 14, 2026 with a $0.15 per-share dividend."
    assert "per-payment" in next(i["source"] for i in q["inputs"] if i["name"] == "dividend per share")


def test_7_usual_move_is_evergreen_past_eight_reports():
    q = Q.q_usual_move(name="Micron Technology", symbol="MU", typical_abs=7.0, n_reports=20, best=(date(2026, 6, 24), 15.7), worst=(date(2024, 12, 18), -16.2), sample_as_of=date(2026, 6, 25))
    assert q["question"] == "How much does Micron Technology usually move on earnings?"
    assert q["data"] == "Over the last 20 reports MU has moved ±7.0% on average the session after reporting; its largest were +15.7% (Jun 24, 2026) and -16.2% (Dec 18, 2024)."
    assert "yardstick" in q["idea"]
    assert_clean(q)
    assert Q.q_usual_move(name="X", symbol="X", typical_abs=3.0, n_reports=7, best=(T, 1.0), worst=(T, -1.0), sample_as_of=T) is None


def test_8_volatile_now_ranks_against_the_stocks_own_year_and_needs_eight_sessions():
    q = Q.q_volatile_now(name="Micron Technology", symbol="MU", rv_20d=0.4153, rv_rank=70.5, sample_days=252, as_of=date(2026, 10, 5))
    assert q["question"] == "Is Micron Technology more volatile than usual right now?"
    assert q["data"] == "MU's realized volatility over the last 20 sessions is 41.5% annualized, more active than 70% of its own 20-day windows over the past year."
    assert_clean(q)
    quiet = Q.q_volatile_now(name="X", symbol="X", rv_20d=0.20, rv_rank=20.0, sample_days=252, as_of=T)
    assert "quieter than 80%" in quiet["data"]
    assert "cause" not in quiet["idea"] and "because" not in quiet["idea"].split("so")[0]
    assert Q.q_volatile_now(name="X", symbol="X", rv_20d=0.2, rv_rank=50.0, sample_days=Q.MIN_SESSIONS - 1, as_of=T) is None


def test_choose_keeps_catalog_order_and_four_at_most():
    qs = [Q.q_beat_fell(name="X", symbol="X", beats=16, fell=9, as_of=T), None, Q.q_ex_dividend(name="X", symbol="X", ex_date=T, amount=1.0, today=T)]
    assert [q["key"] for q in Q.choose(qs)] == ["beat_fell", "ex_dividend"]
    many = [Q.q_beat_fell(name="X", symbol="X", beats=16, fell=9, as_of=T)] * 6
    assert len(Q.choose(many)) == Q.MAX_QUESTIONS == 4


def test_no_number_in_an_answer_is_a_literal_of_its_template():
    a = [Q.q_reaction_normal(name="A", symbol="A", event_date=date(2026, 9, 30), timing="amc", move_pct=3.0, typical_abs=7.0, larger_count=15, n_reports=20, sample_as_of=date(2026, 6, 25)),
         Q.q_implied_big(name="A", symbol="A", implied_pct=0.06, chain_date=date(2026, 10, 5), next_date=date(2026, 10, 6), typical_abs=4.0, n_reports=20, sample_as_of=date(2026, 7, 1)),
         Q.q_beat_fell(name="A", symbol="A", beats=18, fell=11, as_of=date(2026, 6, 25)),
         Q.q_big_move(name="A", symbol="A", move_date=date(2026, 9, 29), move_pct=-26.5, typical_abs=1.6, multiple=16.6, smaller_share=99.84, n_sessions=1254),
         Q.q_upgrades(name="A", symbol="A", upgrades_30d=1, upgrade_sessions=17, median_1d=1.8, continuation_pct=70.6, sample_5d=17, stats_as_of=date(2026, 10, 6), newest_upgrade=date(2026, 9, 30)),
         Q.q_ex_dividend(name="A", symbol="A", ex_date=date(2026, 10, 14), amount=0.6, today=T)]
    b = [Q.q_reaction_normal(name="B", symbol="B", event_date=date(2025, 4, 23), timing="bmo", move_pct=-8.8, typical_abs=5.4, larger_count=9, n_reports=36, sample_as_of=date(2025, 1, 29)),
         Q.q_implied_big(name="B", symbol="B", implied_pct=0.093, chain_date=date(2025, 4, 11), next_date=date(2025, 4, 29), typical_abs=5.4, n_reports=36, sample_as_of=date(2025, 1, 29)),
         Q.q_beat_fell(name="B", symbol="B", beats=27, fell=19, as_of=date(2025, 1, 29)),
         Q.q_big_move(name="B", symbol="B", move_date=date(2025, 4, 8), move_pct=12.4, typical_abs=2.2, multiple=5.6, smaller_share=98.7, n_sessions=1113),
         Q.q_upgrades(name="B", symbol="B", upgrades_30d=3, upgrade_sessions=22, median_1d=0.7, continuation_pct=55.0, sample_5d=22, stats_as_of=date(2025, 4, 13), newest_upgrade=date(2025, 4, 2)),
         Q.q_ex_dividend(name="B", symbol="B", ex_date=date(2025, 4, 24), amount=1.35, today=date(2025, 4, 14))]
    for qa, qb in zip(a, b):
        assert qa and qb and qa["key"] == qb["key"]
        shared = numbers(qa["data"]) & numbers(qb["data"])
        assert shared <= numbers(qa["rule"]) | numbers(qb["rule"]) | {"5"}, (qa["key"], shared)      # "5 years" is RANK_YEARS, named in the rule
        assert_clean(qa); assert_clean(qb)


@pytest.mark.asyncio
async def test_the_route_serves_at_most_four_in_catalog_order_with_receipts():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    order = ["reaction_normal", "implied_big", "beat_fell", "big_move", "upgrades", "ex_dividend", "usual_move", "volatile_now"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for sym in ("MU", "MSFT", "FICO", "STZ", "VMRK"):
            body = (await c.get(f"/api/v1/tickers/{sym}/questions")).json()
            keys = [q["key"] for q in body["questions"]]
            assert len(keys) <= 4 and keys == sorted(keys, key=order.index)
            for q in body["questions"]:
                assert_clean(q)
            if sym != "VMRK":
                assert len(keys) >= 3, (sym, keys)                                             # eight reports or more: three questions at least
        assert (await c.get("/api/v1/tickers/CAG/questions")).json()["questions"] == []       # inactive: nothing
