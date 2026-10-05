"""The briefing: each sentence from fixtures, absent data omitted, the reported-state branch, and no number in a
sentence that is not one of its inputs."""
import re
from datetime import date

import pytest

from app.services import briefing as B
from app.scripts.pick_featured_example import FEATURED_MIN_QUARTERS, choose_featured

T = date(2026, 10, 5)             # a Monday
NUM = re.compile(r"(?<![\d:])\d+(?:,\d{3})*(?:\.\d+)?(?![\d:])")      # numbers, not the digits of a clock time


def numbers(text: str) -> set[str]:
    return set(NUM.findall(text))


def receipts(s: dict) -> str:
    """Every input's value, every input's date in the text's own date format, and the rule."""
    dated = [B.fmt_date(date.fromisoformat(i["as_of"])) for i in s["inputs"] if i["as_of"] and len(i["as_of"]) == 10 and i["as_of"][4] == "-"]
    return " ".join(i["value"] for i in s["inputs"]) + " " + " ".join(dated) + " " + s["rule"]


def assert_receipted(s: dict):
    """Every number in the text is one of the sentence's inputs or a constant its rule names."""
    missing = [n for n in numbers(s["text"]) if n not in receipts(s)]
    assert not missing, (missing, s["text"])


# ── 1. position ──────────────────────────────────────────────────────────────

def test_position_is_one_price_against_the_bars_with_the_last_close_only_in_the_receipt():
    s = B.position_sentence("MU", quote_price=187.52, quote_ts=1791230400, last_close=185.10, last_close_date=date(2026, 10, 2),
                            high_52w=201.00, high_52w_date=date(2026, 9, 12), anchor_close_3m=153.20, anchor_date_3m=date(2026, 7, 6),
                            rv_rank=74.0, rv_as_of=date(2026, 10, 2))
    assert s["text"] == ("MU last traded at $187.52 (Oct 5, 4:00 PM ET), 6.7% below its 52-week high of $201.00 set Sep 12, 2026, up 22.4% over three months. "
                         "Its 20-day realized range is more active than 74% of its past year's 20-day windows (elevated for this stock, as of Oct 2, 2026).")
    assert "$185.10" not in s["text"] and {"name": "last close", "value": "$185.10", "as_of": "2026-10-02", "source": "stored daily bars (price_bars_shadow)"} in s["inputs"]
    assert {"name": "three-month anchor close", "value": "$153.20", "as_of": "2026-07-06", "source": "first stored close on or after 92 calendar days back"} in s["inputs"]
    assert s["key"] == "position" and s["as_of"] == "2026-10-05" and "rank 70 to 89" in s["rule"]
    assert_receipted(s)
    assert B.range_phrase(20.0) == ("quieter than 80%", "80%") and B.range_phrase(50.0) == ("more active than 50%", "50%")
    # no quote: no price, no distance, no change; the range alone
    s = B.position_sentence("MU", last_close=185.10, last_close_date=date(2026, 10, 2), high_52w=201.0, high_52w_date=date(2026, 9, 12), rv_rank=20.0, rv_as_of=date(2026, 10, 2))
    assert s["text"] == "Its 20-day realized range is quieter than 80% of its past year's 20-day windows (quiet for this stock, as of Oct 2, 2026)."
    assert B.position_sentence("MU") is None
    assert B.position_sentence("MU", quote_price=10.0, quote_ts=None) is None          # a price without its time is not shown
    s = B.position_sentence("MU", quote_price=201.0, quote_ts=1791230400, high_52w=201.0, high_52w_date=date(2026, 10, 2))
    assert s["text"] == "MU last traded at $201.00 (Oct 5, 4:00 PM ET), at a 52-week high."


# ── 2. catalyst and the reported state ───────────────────────────────────────

def test_catalyst_names_the_next_report_its_confidence_the_implied_move_and_the_average():
    s = B.catalyst_sentence(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", note="confirmed: press release via Finnhub news 2026-09-10: Micron Announces Fiscal Q4 Date", source="finnhub", timing="amc",
                            implied_pct=0.087, chain_date=date(2026, 10, 2), expiration=date(2026, 10, 17), avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25))
    assert s["text"] == ("Next earnings Oct 14, 2026, after the close, 9 days away, confirmed by the company (press release via Finnhub news 2026-09-10); options imply a move "
                         "of about ±8.7% through Oct 17, 2026 (chain dated Oct 2, 2026); its average 1-day move over the last 20 reports has been ±6.3%.")
    assert_receipted(s)
    s = B.catalyst_sentence(today=T, next_date=date(2026, 12, 16), confirmation="estimated", source="yfinance", avg_abs_1d=4.0, sample_n=8, sample_as_of=date(2026, 9, 1))
    assert s["text"] == "Next earnings Dec 16, 2026, 72 days away, an estimate (Yahoo Finance); its average 1-day move over the last 8 reports has been ±4.0%."
    assert "yfinance" not in s["text"]                                                  # plumbing names stay out of the sentence
    assert "imply" not in s["text"]                                                   # no fresh chain, no implied move
    s = B.catalyst_sentence(today=T, next_date=T, confirmation="expected_unconfirmed")
    assert s["text"] == "Next earnings Oct 5, 2026, today, expected around then, not confirmed."
    assert B.catalyst_sentence(today=T) is None


def test_reported_state_for_an_after_close_reporter_inside_the_window_then_after_settlement():
    assert B.move_dates(date(2026, 10, 2), "amc") == (date(2026, 10, 2), date(2026, 10, 5)) and B.move_dates(date(2026, 10, 5), "bmo") == (date(2026, 10, 2), date(2026, 10, 5))
    assert B.in_reaction_window(date(2026, 10, 2), T) and not B.in_reaction_window(date(2026, 9, 20), T) and not B.in_reaction_window(date(2026, 10, 6), T)
    # reported Friday after the close; on Monday, with Monday's bar not yet stored, the 1-day move settles at today's close
    s = B.reported_sentence(today=date(2026, 10, 5), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat", bars_through=date(2026, 10, 2))
    assert s["text"] == "Reported Oct 2, 2026 after the close: EPS $2.03 against a $1.91 estimate, a beat; the 1-day move settles at today's close."
    assert_receipted(s)
    # the same report seen on the Friday evening: it settles at the next session's close
    s = B.reported_sentence(today=date(2026, 10, 2), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat")
    assert s["text"].endswith("the 1-day move settles at the close on Oct 5, 2026.")
    # once both bars exist the move is read from them, labelled with both closes
    s = B.reported_sentence(today=date(2026, 10, 5), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat", pct_change_1d=-4.8, bars_through=date(2026, 10, 5))
    assert s["text"] == "Reported Oct 2, 2026 after the close: EPS $2.03 against a $1.91 estimate, a beat; the 1-day move (close Oct 2, 2026 to close Oct 5, 2026) was -4.8%."
    assert_receipted(s)
    # a before-the-open reporter: prior close to the report day's close; EPS absent reads as not yet reported to us
    s = B.reported_sentence(today=date(2026, 10, 5), event_date=date(2026, 10, 5), timing="bmo", bars_through=date(2026, 10, 2))
    assert s["text"] == "Reported Oct 5, 2026 before the open: EPS not yet reported to us; the 1-day move settles at today's close."
    s = B.reported_sentence(today=date(2026, 10, 6), event_date=date(2026, 10, 5), timing="bmo", pct_change_1d=1.25)
    assert s["text"].endswith("the 1-day move (close Oct 2, 2026 to close Oct 5, 2026) was +1.2%.")
    # the window has closed but the bar never arrived: said, not estimated
    s = B.reported_sentence(today=date(2026, 10, 7), event_date=date(2026, 10, 2), timing="amc", bars_through=date(2026, 10, 2))
    assert s["text"].endswith("the 1-day move (close Oct 2, 2026 to close Oct 5, 2026) is not yet stored.")
    s = B.reported_sentence(today=date(2026, 10, 5), event_date=date(2026, 10, 5), timing="unknown")
    assert "recorded once the report timing is known" in s["text"]


@pytest.mark.asyncio
async def test_the_builder_reads_the_move_from_the_stored_bars_with_the_seeders_window():
    from app.services.briefing_build import move_from_bars
    from app.services import price_bars
    from app.database import ScriptSessionLocal
    async with ScriptSessionLocal() as s:
        df = await price_bars.bars(s, "MSFT", date(2026, 7, 1))
        rows = (await s.execute(__import__("sqlalchemy").text(
            "SELECT event_date, report_timing, pct_change_1d FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id "
            "WHERE t.symbol = 'MSFT' AND hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL AND hr.event_date >= '2026-07-01' ORDER BY event_date DESC LIMIT 1"))).first()
    if rows is None or df.empty:
        pytest.skip("no recent MSFT reaction stored locally")
    got = move_from_bars(df, rows[0], rows[1])
    assert got is not None and abs(got - float(rows[2])) < 0.011          # the stored row and the live window agree (same function, same bars)
    assert move_from_bars(df, date(2026, 10, 2), "unknown") is None


# ── 3. pattern ───────────────────────────────────────────────────────────────

def test_pattern_reads_a_beat_as_no_signal_at_the_threshold_and_needs_a_sample():
    s = B.pattern_sentence(total=20, beat_count=15, fell_after_beat=8, as_of=date(2026, 6, 25))
    assert s["text"] == "Beat estimates in 15 of the last 20 reports and fell the next session after 8 of those 15 beats (53%), so a beat alone has not been a buy signal."
    assert "stored" not in s["text"]
    assert_receipted(s) and f"{B.BEAT_NOT_SIGNAL_SHARE}%" in s["rule"]
    s = B.pattern_sentence(total=20, beat_count=16, fell_after_beat=8, as_of=date(2026, 6, 25))     # exactly 50%
    assert "has not been a buy signal" in s["text"]
    s = B.pattern_sentence(total=12, beat_count=10, fell_after_beat=2, as_of=date(2026, 6, 25), basis_excluded=1)
    assert s["text"].endswith("(20%), so a beat has usually been followed by a gain.") and "1 quarter(s) with an unclear EPS basis excluded" in s["rule"]
    assert B.pattern_sentence(total=B.MIN_QUARTERS - 1, beat_count=2, fell_after_beat=1, as_of=T) is None
    assert B.pattern_sentence(total=10, beat_count=0, fell_after_beat=0, as_of=T) is None


# ── 4. street ────────────────────────────────────────────────────────────────

def test_street_counts_recent_actions_and_the_median_target_and_reads_the_upgrade_day_stat():
    acts = [{"date": date(2026, 9, 30), "action": "up", "price_target": "210"}, {"date": date(2026, 9, 1), "action": "up", "price_target": "190"},
            {"date": date(2026, 8, 20), "action": "down", "price_target": None}, {"date": date(2026, 7, 20), "action": "init", "price_target": "200"},
            {"date": date(2026, 5, 1), "action": "up", "price_target": "150"}]        # outside 90 days
    s = B.street_sentence(today=T, actions=acts, median_1d_upgrade=1.2, upgrade_sessions=14, stats_as_of=date(2026, 10, 4))
    assert s["text"] == ("Over the last 90 days analysts made 2 upgrades, 1 downgrade and 1 initiation, median price target $200.00; "
                         "on upgrade days this stock's median move has been +1.2% across 14 upgrade sessions.")
    assert_receipted(s) and s["as_of"] == "2026-10-04"
    kept = B.street_sentence(today=T, actions=[{"date": date(2026, 9, 9), "action": "main", "price_target": "120"}])
    assert kept["text"] == "Over the last 90 days analysts made no upgrades, downgrades or initiations, median price target $120.00."
    only_init = B.street_sentence(today=T, actions=[{"date": date(2026, 9, 9), "action": "init", "price_target": None}])
    assert only_init["text"] == "Over the last 90 days analysts made 1 initiation."          # zero counts are not spoken
    s = B.street_sentence(today=T, actions=[], median_1d_upgrade=-0.4, upgrade_sessions=5, stats_as_of=date(2026, 10, 4))
    assert s["text"] == "On upgrade days this stock's median move has been -0.4% across 5 upgrade sessions."
    assert B.street_sentence(today=T, actions=[]) is None


# ── 5. risk ──────────────────────────────────────────────────────────────────

def test_risk_names_the_worst_and_best_moves_with_their_dates():
    moves = [(date(2024, 6, 26), -12.3), (date(2023, 9, 27), 18.0), (date(2025, 3, 20), 2.1), (date(2025, 6, 25), -0.5)]
    s = B.risk_sentence(moves=moves)
    assert s["text"] == "Across the last 4 reports, the worst 1-day move was -12.3% (Jun 26, 2024) and the best +18.0% (Sep 27, 2023)."
    assert_receipted(s) and s["as_of"] == "2025-06-25"
    assert B.risk_sentence(moves=moves[:B.MIN_QUARTERS - 1]) is None


# ── nothing numeric lives in a template ──────────────────────────────────────

def test_no_number_in_a_sentence_is_a_literal_of_its_template():
    """Two fixtures with disjoint numbers: a number present in both texts can only be a constant the rule names."""
    a = [B.position_sentence("MU", quote_price=187.52, quote_ts=1791230400, last_close=185.10, last_close_date=date(2026, 10, 2), high_52w=201.0, high_52w_date=date(2026, 9, 12),
                             anchor_close_3m=153.2, anchor_date_3m=date(2026, 7, 6), rv_rank=74.0, rv_as_of=date(2026, 10, 2)),
         B.catalyst_sentence(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2),
                             expiration=date(2026, 10, 17), avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25)),
         B.pattern_sentence(total=20, beat_count=15, fell_after_beat=8, as_of=date(2026, 6, 25)),
         B.street_sentence(today=T, actions=[{"date": date(2026, 9, 30), "action": "up", "price_target": "210"}], median_1d_upgrade=1.2, upgrade_sessions=14, stats_as_of=date(2026, 10, 4)),
         B.risk_sentence(moves=[(date(2024, 6, 26), -12.3), (date(2023, 9, 27), 18.0), (date(2025, 3, 20), 2.1), (date(2025, 6, 25), -0.5)])]
    b = [B.position_sentence("ZZ", quote_price=43.11, quote_ts=1744398000, last_close=41.77, last_close_date=date(2025, 4, 11), high_52w=66.6, high_52w_date=date(2025, 1, 3),
                             anchor_close_3m=48.8, anchor_date_3m=date(2025, 1, 13), rv_rank=31.0, rv_as_of=date(2025, 4, 11)),
         B.catalyst_sentence(today=date(2025, 4, 14), next_date=date(2025, 4, 29), confirmation="estimated", source="x", timing="bmo", implied_pct=0.041, chain_date=date(2025, 4, 11),
                             expiration=date(2025, 5, 8), avg_abs_1d=3.3, sample_n=36, sample_as_of=date(2025, 1, 29)),
         B.pattern_sentence(total=36, beat_count=27, fell_after_beat=19, as_of=date(2025, 1, 29)),
         B.street_sentence(today=date(2025, 4, 14), actions=[{"date": date(2025, 4, 1), "action": "down", "price_target": "55"}] * 3, median_1d_upgrade=0.7, upgrade_sessions=9, stats_as_of=date(2025, 4, 13)),
         B.risk_sentence(moves=[(date(2021, 7, 29), -23.4), (date(2022, 1, 21), 11.1), (date(2022, 4, 28), 3.3), (date(2022, 7, 28), -6.6)] * 9)]
    for sa, sb in zip(a, b):
        assert sa and sb and sa["key"] == sb["key"]
        shared = numbers(sa["text"]) & numbers(sb["text"])
        assert shared <= numbers(sa["rule"]) | numbers(sb["rule"]), (sa["key"], shared)
        assert_receipted(sa); assert_receipted(sb)
    for const in (B.WINDOW_52W_DAYS, B.WINDOW_3M_DAYS, B.STREET_DAYS, B.REACTION_WINDOW_SESSIONS, B.BEAT_NOT_SIGNAL_SHARE, B.MIN_QUARTERS):
        assert isinstance(const, int)


def test_no_plumbing_words_in_any_sentence_text():
    texts = [x["text"] for x in (
        B.position_sentence("MU", quote_price=187.52, quote_ts=1791230400, last_close=185.1, last_close_date=date(2026, 10, 2), high_52w=201.0, high_52w_date=date(2026, 9, 12),
                            anchor_close_3m=153.2, anchor_date_3m=date(2026, 7, 6), rv_rank=74.0, rv_as_of=date(2026, 10, 2)),
        B.catalyst_sentence(today=T, next_date=date(2026, 12, 16), confirmation="estimated", source="yfinance", avg_abs_1d=4.0, sample_n=8, sample_as_of=date(2026, 9, 1)),
        B.reported_sentence(today=T, event_date=date(2026, 10, 2), timing="amc", pct_change_1d=1.0),
        B.pattern_sentence(total=20, beat_count=15, fell_after_beat=8, as_of=date(2026, 6, 25)),
        B.street_sentence(today=T, actions=[{"date": date(2026, 9, 30), "action": "up", "price_target": "210"}], median_1d_upgrade=1.2, upgrade_sessions=14, stats_as_of=date(2026, 10, 4)),
        B.risk_sentence(moves=[(date(2024, 6, 26), -12.3), (date(2023, 9, 27), 18.0), (date(2025, 3, 20), 2.1), (date(2025, 6, 25), -0.5)]))]
    for t in texts:
        assert not re.search(r"stored|yfinance|finnhub|the street|rv_rank|out of 100|_", t), t


# ── the featured example ─────────────────────────────────────────────────────

def test_featured_pick_is_the_nearest_confirmed_report_with_enough_quarters_ties_to_market_cap():
    cands = [{"symbol": "A", "earnings_date": date(2026, 10, 14), "confirmation": "estimated", "quarters": 40, "market_cap": 9e12},
             {"symbol": "B", "earnings_date": date(2026, 10, 15), "confirmation": "confirmed", "quarters": 19, "market_cap": 9e12},
             {"symbol": "C", "earnings_date": date(2026, 10, 16), "confirmation": "confirmed", "quarters": 20, "market_cap": 1e9},
             {"symbol": "D", "earnings_date": date(2026, 10, 16), "confirmation": "confirmed", "quarters": 24, "market_cap": 5e9},
             {"symbol": "E", "earnings_date": None, "confirmation": "confirmed", "quarters": 60, "market_cap": 1e12}]
    assert choose_featured(cands)["symbol"] == "D" and FEATURED_MIN_QUARTERS == 20
    assert choose_featured(cands[:2]) is None


@pytest.mark.asyncio
async def test_the_route_serves_dated_receipted_sentences_and_the_home_block_reads_two_of_them():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/tickers/MU/briefing")).json()
        assert body["symbol"] == "MU" and body["sentences"]
        keys = [s["key"] for s in body["sentences"]]
        assert keys == sorted(keys, key=["position", "catalyst", "pattern", "street", "risk"].index)
        for s in body["sentences"]:
            assert s["as_of"] and s["rule"] and s["inputs"]
            assert_receipted(s)
        assert (await c.get("/api/v1/tickers/ZZNOPE/briefing")).status_code == 404
        feat = (await c.get("/api/v1/discover/featured")).json()
        assert set(s["key"] for s in feat["sentences"]) <= {"catalyst", "pattern"}
        if feat["symbol"]:
            assert feat["picked_on"] and feat["earnings_date"] and feat["rule"]
