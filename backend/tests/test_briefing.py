"""The Overview's two blocks from fixtures: every sentence-B branch and its omissions, the description cap, plain-words
market cap, no literal numbers in templates, no plumbing words in visible text, and the route."""
import re
from datetime import date, timedelta

import pytest

from app.services import briefing as B
from app.scripts.pick_featured_example import FEATURED_MIN_QUARTERS, choose_featured

T = date(2026, 10, 5)             # a Monday
NUM = re.compile(r"(?<![\d:])\d+(?:,\d{3})*(?:\.\d+)?(?![\d:])")      # numbers, not the digits of a clock time
PLUMBING = re.compile(r"stored|yfinance|finnhub|rv_rank|quarters|the street|out of 100|_", re.I)
QUOTE_TS = 1791230400             # 2026-10-05 20:00Z, 4:00 PM EDT
STOCK = dict(quote_price=187.52, quote_ts=QUOTE_TS, last_close=185.10, last_close_date=date(2026, 10, 2), high_52w=201.00, high_52w_date=date(2026, 9, 12),
             anchor_close_3m=153.20, anchor_date_3m=date(2026, 7, 6))


def numbers(text: str) -> set[str]:
    return set(NUM.findall(text))


def receipts(s: dict) -> str:
    dated = [B.fmt_date(date.fromisoformat(i["as_of"])) for i in s["inputs"] if i["as_of"] and len(i["as_of"]) == 10 and i["as_of"][4] == "-"]
    return " ".join(i["value"] for i in s["inputs"]) + " " + " ".join(dated) + " " + s["rule"]


def assert_clean(s: dict):
    """Every number in the text is an input or a constant the rule names; no plumbing word is visible."""
    missing = [n for n in numbers(s["text"]) if n not in receipts(s)]
    assert not missing, (missing, s["text"])
    assert not PLUMBING.search(s["text"]), s["text"]


# ── block 1 ──────────────────────────────────────────────────────────────────

def test_profile_quotes_the_description_then_one_built_sentence():
    desc = "Micron Technology, Inc. designs, manufactures, and sells memory and storage products. The company operates through four segments. It sells to OEMs."
    s = B.profile_sentence(name="Micron Technology, Inc.", short_description=desc, sector="Manufacturing", industry="Electronic Equipment", index_member=True,
                           profile_as_of=date(2026, 10, 5), market_cap=1.19e12, market_cap_as_of=date(2026, 10, 2))
    assert s["text"] == ("Micron Technology, Inc. designs, manufactures, and sells memory and storage products. The company operates through four segments. "
                         "Micron Technology, Inc. is part of the S&P 500's Manufacturing sector (Electronic Equipment), worth about $1.2 trillion.")
    assert s["key"] == "profile" and s["as_of"] == "2026-10-05"
    assert {"name": "market cap", "value": "$1.2 trillion", "as_of": "2026-10-02", "source": "tickers.market_cap (Finnhub profile), in round words"} in s["inputs"]
    assert_clean(s)
    s = B.profile_sentence(name="Conagra Brands, Inc.", short_description="Conagra makes food.", sector="Manufacturing", industry="Food", index_member=False, profile_as_of=T)
    assert s["text"] == "Conagra makes food. Conagra Brands, Inc. is in the Manufacturing sector (Food)."        # no S&P claim off the list, no value without a dated cap
    assert B.profile_sentence(name="X") is None
    assert B.profile_sentence(short_description="A bank.", profile_as_of=T)["text"] == "A bank."


def test_description_is_whole_sentences_within_the_cap_without_boilerplate():
    long1 = "Alpha Corp. " + "makes very many kinds of industrial equipment for customers in energy, mining and construction " * 3 + "around the world."
    assert len(long1) > B.DESCRIPTION_CAP
    assert B.description_text(long1 + " Second sentence.") == long1                       # a lone first sentence may exceed the cap, never cut
    two = "Alpha Corp. makes equipment. " + "It sells through dealers in " + ", ".join(f"region {i}" for i in range(40)) + "."
    assert B.description_text(two) == "Alpha Corp. makes equipment."                      # the second sentence would breach the cap, so it is dropped whole
    assert B.description_text("One. Two. Three.") == "One. Two."
    assert B.description_text("Beta Inc. sells shoes. The company was incorporated in 1998 and is headquartered in Ohio. It has 40 stores.") == "Beta Inc. sells shoes. It has 40 stores."
    assert B.description_text("Gamma Co. was formerly known as Delta. Gamma Co. makes glass.") == "Gamma Co. makes glass."
    assert B.description_text(None) is None and B.description_text("") is None
    assert B.split_sentences("Acme Corp. builds in the U.S. market. Second here. Third.") == ["Acme Corp. builds in the U.S. market.", "Second here.", "Third."]


def test_market_value_in_plain_words_one_decimal_at_most():
    assert [B.market_value_words(v) for v in (1.19e12, 19.4e9, 850e6, 9.96e9, 2.5e6)] == ["$1.2 trillion", "$19 billion", "$850 million", "$10.0 billion", "$2.5 million"]
    assert B.market_value_words(None) is None and B.market_value_words(0) is None


# ── block 2, sentence A ──────────────────────────────────────────────────────

def test_stock_sentence_names_the_quote_the_high_and_the_three_month_change_or_near_the_high():
    text, inputs, dates = B.stock_sentence("MU", **STOCK)
    assert text == "MU is at $187.52 (Oct 5, 4:00 PM ET), 6.7% below its 52-week high of $201.00 (Sep 12, 2026), up 22.4% over three months."
    assert "$185.10" not in text and any(i["name"] == "last close" and i["value"] == "$185.10" for i in inputs) and dates == [date(2026, 10, 5)]
    text, _, _ = B.stock_sentence("MU", quote_price=198.5, quote_ts=QUOTE_TS, high_52w=201.0, high_52w_date=date(2026, 9, 12), anchor_close_3m=220.0, anchor_date_3m=date(2026, 7, 6))
    assert text == "MU is at $198.50 (Oct 5, 4:00 PM ET), near its 52-week high of $201.00 (Sep 12, 2026), down 9.8% over three months."
    assert B.stock_sentence("MU", quote_price=10.0, quote_ts=None) is None                 # a price without its time is not shown


# ── block 2, sentence B: each branch and its omissions ──────────────────────

def test_branch_1_reported_state_with_and_without_eps_before_and_after_settlement():
    t, _, _ = B.reported_clause(today=date(2026, 10, 5), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat", pct_change_1d=-4.8)
    assert t == "Reported Oct 2, 2026 after the close: EPS $2.03 against a $1.91 estimate, a beat; the stock moved -4.8% the next session."
    t, _, _ = B.reported_clause(today=date(2026, 10, 5), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat", bars_through=date(2026, 10, 2))
    assert t == "Reported Oct 2, 2026 after the close: EPS $2.03 against a $1.91 estimate, a beat; the move settles at today's close."
    t, _, _ = B.reported_clause(today=date(2026, 10, 5), event_date=date(2026, 10, 5), timing="bmo", bars_through=date(2026, 10, 2))
    assert t == "Reported Oct 5, 2026 before the open: the move settles at today's close."                           # no actual: no EPS clause
    t, _, _ = B.reported_clause(today=date(2026, 10, 6), event_date=date(2026, 10, 5), timing="bmo", eps_actual=1.0, eps_estimate=1.0, outcome="meet", pct_change_1d=1.25)
    assert t == "Reported Oct 5, 2026 before the open: EPS $1.00 against a $1.00 estimate, a match; the stock moved +1.2% that session."
    assert B.reported_clause(today=date(2026, 10, 2), event_date=date(2026, 10, 2), timing="amc")[0].endswith("the move settles at the close on Oct 5, 2026.")
    assert B.reported_clause(today=date(2026, 10, 7), event_date=date(2026, 10, 2), timing="amc", bars_through=date(2026, 10, 2))[0].endswith("(close Oct 2, 2026 to close Oct 5, 2026) is not yet stored.")
    assert "recorded once the report timing is known" in B.reported_clause(today=T, event_date=T, timing="unknown")[0]
    assert B.in_reaction_window(date(2026, 10, 2), T) and not B.in_reaction_window(date(2026, 9, 20), T)


def test_branch_2_big_move_is_the_largest_off_earnings_move_at_least_three_times_a_typical_day():
    sessions = [T - timedelta(days=i) for i in range(400, 0, -1) if (T - timedelta(days=i)).weekday() < 5]
    daily = [(d, 0.8 if i % 2 else -0.8) for i, d in enumerate(sessions)]                  # a typical day is 0.8%
    daily[-3] = (daily[-3][0], -7.0)                                                        # an earnings day
    daily[-10] = (daily[-10][0], 4.0)                                                       # 5x typical, not earnings
    big = B.find_big_move(daily, exclude={daily[-3][0], daily[-2][0]}, today=T)
    assert big["move_date"] == daily[-10][0] and big["move_pct"] == 4.0 and big["typical_abs"] == 0.8 and round(big["multiple"]) == 5
    t, inputs, _ = B.big_move_clause(**big)
    assert t == f"Its biggest move in the past month was +4.0% on {B.fmt_date(daily[-10][0])}, about 5 times a typical day for this stock."
    assert "news" not in t and "because" not in t                                           # no cause stated
    assert B.find_big_move([(d, 0.8) for d in sessions], set(), T) is None                  # nothing unusual
    assert B.find_big_move(daily[-30:], set(), T) is None                                   # too little history for a typical day
    daily2 = list(daily); daily2[-10] = (daily2[-10][0], 2.3)                               # under 3x
    assert B.find_big_move(daily2, {daily[-3][0], daily[-2][0]}, T) is None


def test_branch_3_next_report_within_45_days_with_the_options_clause_only_on_a_fresh_chain():
    t, _, _ = B.upcoming_clause(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", note="confirmed: press release via Finnhub news 2026-09-10: Q4 date", source="finnhub",
                                timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2), avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25))
    assert t == "Reports Oct 14, 2026 after the close, 9 days away (confirmed by the company); options price a move of about ±8.7% against a typical ±6.3%."
    t, _, _ = B.upcoming_clause(today=T, next_date=date(2026, 10, 6), confirmation="estimated", source="yfinance", timing="bmo", avg_abs_1d=4.0, sample_n=8)
    assert t == "Reports Oct 6, 2026 before the open, 1 day away (estimated)."                  # no fresh chain: no options clause
    assert B.upcoming_clause(today=T, next_date=T, confirmation="expected_unconfirmed")[0] == "Reports Oct 5, 2026, today (expected, not confirmed)."


def test_sentence_b_priority_and_omission():
    rep = dict(today=T, event_date=date(2026, 9, 30), timing="amc", eps_actual=3.03, eps_estimate=2.86, outcome="beat", pct_change_1d=3.0)
    big = dict(move_date=date(2026, 9, 25), move_pct=-9.1, typical_abs=1.3, multiple=7.0)
    up = dict(today=T, next_date=date(2026, 10, 28), confirmation="estimated", source="yfinance", timing="amc")
    s = B.happening_sentence("MU", stock=STOCK, reported=rep, big_move=big, upcoming=up)
    assert "Reported Sep 30, 2026" in s["text"] and "biggest move" not in s["text"] and "Reports" not in s["text"]
    assert s["key"] == "happening" and s["as_of"] == "2026-10-05"
    assert_clean(s)
    s = B.happening_sentence("MU", stock=STOCK, big_move=big, upcoming=up)
    assert "biggest move" in s["text"] and "Reports" not in s["text"]
    assert_clean(s)
    s = B.happening_sentence("MU", stock=STOCK, upcoming=up)
    assert s["text"].endswith("Reports Oct 28, 2026 after the close, 23 days away (estimated).")
    s = B.happening_sentence("MU", stock=STOCK, upcoming=dict(today=T, next_date=T + timedelta(days=B.NEXT_WITHIN_DAYS + 1)))
    assert s["text"] == B.stock_sentence("MU", **STOCK)[0]                                  # beyond 45 days: sentence B omitted
    assert B.happening_sentence("MU", stock=dict(quote_price=None, quote_ts=None)) is None
    assert B.happening_sentence("MU") is None


# ── nothing numeric lives in a template; no plumbing words ──────────────────

def test_no_number_in_a_block_is_a_literal_of_its_template():
    a = [B.profile_sentence(name="Alpha", short_description="Alpha makes chips.", sector="Manufacturing", industry="Semiconductors", index_member=True, profile_as_of=date(2026, 10, 5), market_cap=1.19e12, market_cap_as_of=date(2026, 10, 2)),
         B.happening_sentence("MU", stock=STOCK, upcoming=dict(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2),
                                                               avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25))),
         B.happening_sentence("MU", stock=STOCK, big_move=dict(move_date=date(2026, 9, 25), move_pct=-9.1, typical_abs=1.3, multiple=7.0))]
    b = [B.profile_sentence(name="Beta", short_description="Beta sells shoes.", sector="Retail", industry="Apparel", index_member=False, profile_as_of=date(2025, 4, 11), market_cap=23.4e9, market_cap_as_of=date(2025, 4, 9)),
         B.happening_sentence("ZZ", stock=dict(quote_price=43.11, quote_ts=1744398000, last_close=41.77, last_close_date=date(2025, 4, 11), high_52w=66.6, high_52w_date=date(2025, 1, 3),
                                               anchor_close_3m=48.8, anchor_date_3m=date(2025, 1, 13)),
                              upcoming=dict(today=date(2025, 4, 14), next_date=date(2025, 4, 29), confirmation="estimated", source="x", timing="bmo", implied_pct=0.041, chain_date=date(2025, 4, 11),
                                            avg_abs_1d=3.3, sample_n=36, sample_as_of=date(2025, 1, 29))),
         B.happening_sentence("ZZ", stock=dict(quote_price=43.11, quote_ts=1744398000, high_52w=66.6, high_52w_date=date(2025, 1, 3), anchor_close_3m=48.8, anchor_date_3m=date(2025, 1, 13)),
                              big_move=dict(move_date=date(2025, 4, 8), move_pct=12.4, typical_abs=2.2, multiple=5.6))]
    for sa, sb in zip(a, b):
        assert sa and sb and sa["key"] == sb["key"]
        shared = numbers(sa["text"]) & numbers(sb["text"])
        assert shared <= numbers(sa["rule"]) | numbers(sb["rule"]), (sa["key"], shared)
        assert_clean(sa); assert_clean(sb)
    for const in (B.WINDOW_52W_DAYS, B.WINDOW_3M_DAYS, B.REACTION_WINDOW_SESSIONS, B.DESCRIPTION_SENTENCES, B.DESCRIPTION_CAP, B.NEAR_HIGH_PCT, B.BIG_MOVE_SESSIONS, B.BIG_MOVE_MULTIPLE, B.NEXT_WITHIN_DAYS):
        assert isinstance(const, int)


# ── the featured example and the route ───────────────────────────────────────

def test_featured_pick_is_the_nearest_confirmed_report_with_enough_quarters_ties_to_market_cap():
    cands = [{"symbol": "A", "earnings_date": date(2026, 10, 14), "confirmation": "estimated", "quarters": 40, "market_cap": 9e12},
             {"symbol": "B", "earnings_date": date(2026, 10, 15), "confirmation": "confirmed", "quarters": 19, "market_cap": 9e12},
             {"symbol": "C", "earnings_date": date(2026, 10, 16), "confirmation": "confirmed", "quarters": 20, "market_cap": 1e9},
             {"symbol": "D", "earnings_date": date(2026, 10, 16), "confirmation": "confirmed", "quarters": 24, "market_cap": 5e9},
             {"symbol": "E", "earnings_date": None, "confirmation": "confirmed", "quarters": 60, "market_cap": 1e12}]
    assert choose_featured(cands)["symbol"] == "D" and FEATURED_MIN_QUARTERS == 20
    assert choose_featured(cands[:2]) is None


@pytest.mark.asyncio
async def test_the_route_serves_the_two_blocks_an_inactive_state_and_the_home_block_reads_the_same_two():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/tickers/MU/briefing")).json()
        assert body["symbol"] == "MU" and [s["key"] for s in body["sentences"]] == ["profile", "happening"] and body["state"] is None
        for s in body["sentences"]:
            assert s["as_of"] and s["rule"] and s["inputs"]
            assert_clean(s)
        cag = (await c.get("/api/v1/tickers/CAG/briefing"))
        assert cag.status_code == 200 and cag.json()["sentences"] == [] and cag.json()["state"]       # inactive: a state, not a page of nothing
        assert (await c.get("/api/v1/tickers/ZZNOPE/briefing")).status_code == 404
        feat = (await c.get("/api/v1/discover/featured")).json()
        assert set(s["key"] for s in feat["sentences"]) <= {"profile", "happening"}


@pytest.mark.asyncio
async def test_the_builder_reads_the_move_from_the_stored_bars_with_the_seeders_window():
    from app.services.briefing_build import move_from_bars
    from app.services import price_bars
    from app.database import ScriptSessionLocal
    from sqlalchemy import text
    async with ScriptSessionLocal() as s:
        df = await price_bars.bars(s, "MSFT", date(2026, 7, 1))
        row = (await s.execute(text(
            "SELECT event_date, report_timing, pct_change_1d FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id "
            "WHERE t.symbol = 'MSFT' AND hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL AND hr.event_date >= '2026-07-01' ORDER BY event_date DESC LIMIT 1"))).first()
    if row is None or df.empty:
        pytest.skip("no recent MSFT reaction stored locally")
    got = move_from_bars(df, row[0], row[1])
    assert got is not None and abs(got - float(row[2])) < 0.011
