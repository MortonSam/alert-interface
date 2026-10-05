"""The Overview's two blocks from fixtures, absent data omitted, the reported-state branch, and no number in a block
that is not one of its inputs."""
import re
from datetime import date

import pytest

from app.services import briefing as B
from app.scripts.pick_featured_example import FEATURED_MIN_QUARTERS, choose_featured

T = date(2026, 10, 5)             # a Monday
NUM = re.compile(r"(?<![\d:])\d+(?:,\d{3})*(?:\.\d+)?(?![\d:])")      # numbers, not the digits of a clock time
QUOTE_TS = 1791230400             # 2026-10-05 20:00Z, 4:00 PM EDT


def numbers(text: str) -> set[str]:
    return set(NUM.findall(text))


def receipts(s: dict) -> str:
    dated = [B.fmt_date(date.fromisoformat(i["as_of"])) for i in s["inputs"] if i["as_of"] and len(i["as_of"]) == 10 and i["as_of"][4] == "-"]
    return " ".join(i["value"] for i in s["inputs"]) + " " + " ".join(dated) + " " + s["rule"]


def assert_receipted(s: dict):
    missing = [n for n in numbers(s["text"]) if n not in receipts(s)]
    assert not missing, (missing, s["text"])


PRICE = dict(quote_price=187.52, quote_ts=QUOTE_TS, last_close=185.10, last_close_date=date(2026, 10, 2), high_52w=201.00, high_52w_date=date(2026, 9, 12),
             anchor_close_3m=153.20, anchor_date_3m=date(2026, 7, 6))


# ── block 1: what it is ──────────────────────────────────────────────────────

def test_profile_quotes_the_stored_description_names_industry_sector_and_market_value_in_words():
    desc = "Micron Technology, Inc. designs, manufactures, and sells memory and storage products. The company operates through four segments. It sells to OEMs."
    s = B.profile_sentence(short_description=desc, sector="Manufacturing", industry="Electronic Equipment", profile_as_of=date(2026, 10, 5),
                           market_cap=1.19e12, market_cap_as_of=date(2026, 10, 2))
    assert s["text"] == ("Micron Technology, Inc. designs, manufactures, and sells memory and storage products. The company operates through four segments. "
                         "It is an Electronic Equipment company in the Manufacturing sector, worth about $1.2 trillion at market as of Oct 2, 2026.")
    assert s["key"] == "profile" and s["as_of"] == "2026-10-05"
    assert_receipted(s)
    assert B.market_value_words(23.4e9) == "$23 billion" and B.market_value_words(640e6) == "$640 million" and B.market_value_words(None) is None
    assert B.first_sentences("One. Two. Three.", 2) == "One. Two." and B.first_sentences("No period", 2) == "No period." and B.first_sentences(None) is None
    s = B.profile_sentence(short_description=None, sector="Finance", industry="Banking", profile_as_of=date(2026, 10, 5))
    assert s["text"] == "It is a Banking company in the Finance sector."
    assert B.profile_sentence() is None
    assert B.profile_sentence(short_description="A bank.", profile_as_of=date(2026, 10, 5), market_cap=5e9)["text"] == "A bank."    # no market-cap date, no value


# ── block 2: what's been happening ──────────────────────────────────────────

def test_price_clause_is_one_price_against_the_bars_with_the_last_close_only_in_the_receipt():
    text, inputs, dates = B.price_clause("MU", **PRICE)
    assert text == "MU last traded at $187.52 (Oct 5, 4:00 PM ET), 6.7% below its 52-week high of $201.00 set Sep 12, 2026, up 22.4% over three months."
    assert "$185.10" not in text and {"name": "last close", "value": "$185.10", "as_of": "2026-10-02", "source": "stored daily bars (price_bars_shadow)"} in inputs
    assert dates == [date(2026, 10, 5)]
    assert B.price_clause("MU", quote_price=10.0, quote_ts=None) is None                    # a price without its time is not shown
    assert B.price_clause("MU", quote_price=201.0, quote_ts=QUOTE_TS, high_52w=201.0, high_52w_date=date(2026, 10, 2))[0] == "MU last traded at $201.00 (Oct 5, 4:00 PM ET), at a 52-week high."


def test_reported_clause_for_an_after_close_reporter_inside_the_window_then_after_settlement():
    assert B.move_dates(date(2026, 10, 2), "amc") == (date(2026, 10, 2), date(2026, 10, 5)) and B.move_dates(date(2026, 10, 5), "bmo") == (date(2026, 10, 2), date(2026, 10, 5))
    assert B.in_reaction_window(date(2026, 10, 2), T) and not B.in_reaction_window(date(2026, 9, 20), T) and not B.in_reaction_window(date(2026, 10, 6), T)
    t, _, _ = B.reported_clause(today=date(2026, 10, 5), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat", bars_through=date(2026, 10, 2))
    assert t == "Reported Oct 2, 2026 after the close, EPS $2.03 against a $1.91 estimate, a beat, and the 1-day move settles at today's close."
    t, _, _ = B.reported_clause(today=date(2026, 10, 2), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat")
    assert t.endswith("and the 1-day move settles at the close on Oct 5, 2026.")
    t, _, _ = B.reported_clause(today=date(2026, 10, 5), event_date=date(2026, 10, 2), timing="amc", eps_actual=2.03, eps_estimate=1.91, outcome="beat", pct_change_1d=-4.8, bars_through=date(2026, 10, 5))
    assert t == "Reported Oct 2, 2026 after the close, EPS $2.03 against a $1.91 estimate, a beat, and the stock moved -4.8% the next session (1-day move, close Oct 2, 2026 to close Oct 5, 2026)."
    t, _, _ = B.reported_clause(today=date(2026, 10, 5), event_date=date(2026, 10, 5), timing="bmo", bars_through=date(2026, 10, 2))
    assert t == "Reported Oct 5, 2026 before the open, EPS not yet reported to us, and the 1-day move settles at today's close."
    t, _, _ = B.reported_clause(today=date(2026, 10, 6), event_date=date(2026, 10, 5), timing="bmo", pct_change_1d=1.25)
    assert t.endswith("the stock moved +1.2% that session (1-day move, close Oct 2, 2026 to close Oct 5, 2026).")
    t, _, _ = B.reported_clause(today=date(2026, 10, 7), event_date=date(2026, 10, 2), timing="amc", bars_through=date(2026, 10, 2))
    assert t.endswith("and the 1-day move (close Oct 2, 2026 to close Oct 5, 2026) is not yet stored.")
    assert "recorded once the report timing is known" in B.reported_clause(today=T, event_date=T, timing="unknown")[0]


def test_upcoming_clause_names_the_report_its_confidence_and_the_implied_move_against_the_typical_one():
    t, inputs, _ = B.upcoming_clause(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", note="confirmed: press release via Finnhub news 2026-09-10: Q4 date", source="finnhub",
                                     timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2), expiration=date(2026, 10, 17), avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25))
    assert t == ("Reports Oct 14, 2026 after the close, 9 days away, confirmed by the company (press release via Finnhub news 2026-09-10); options price about ±8.7% "
                 "through Oct 17, 2026 (chain dated Oct 2, 2026) against a typical ±6.3% over the last 20 reports.")
    t, _, _ = B.upcoming_clause(today=T, next_date=date(2026, 12, 16), confirmation="estimated", source="yfinance", avg_abs_1d=4.0, sample_n=8, sample_as_of=date(2026, 9, 1))
    assert t == "Reports Dec 16, 2026, 72 days away, an estimate (Yahoo Finance); its typical move has been ±4.0% over the last 8 reports."
    assert "yfinance" not in t
    assert B.upcoming_clause(today=T, next_date=T, confirmation="expected_unconfirmed")[0] == "Reports Oct 5, 2026, today, expected around then, not confirmed."


def test_happening_block_prefers_the_reported_state_and_omits_what_is_absent():
    s = B.happening_sentence("MU", price=PRICE, reported=dict(today=T, event_date=date(2026, 9, 30), timing="amc", eps_actual=3.03, eps_estimate=2.86, outcome="beat", pct_change_1d=3.0),
                             upcoming=dict(today=T, next_date=date(2026, 12, 16)))
    assert s["text"].startswith("MU last traded at $187.52") and "Reported Sep 30, 2026 after the close" in s["text"] and "Reports Dec" not in s["text"]
    assert s["key"] == "happening" and s["as_of"] == "2026-10-05"
    assert_receipted(s)
    s = B.happening_sentence("MU", price=dict(quote_price=None, quote_ts=None), upcoming=dict(today=T, next_date=date(2026, 12, 16), confirmation="estimated", source="finnhub"))
    assert s["text"] == "Reports Dec 16, 2026, 72 days away, an estimate (Finnhub)."                  # no quote: no price clause
    assert B.happening_sentence("MU", price=dict(quote_price=None, quote_ts=None)) is None
    assert B.happening_sentence("MU") is None


# ── nothing numeric lives in a template; no plumbing words reach the text ────

def test_no_number_in_a_block_is_a_literal_of_its_template():
    a = [B.profile_sentence(short_description="Alpha makes chips.", sector="Manufacturing", industry="Semiconductors", profile_as_of=date(2026, 10, 5), market_cap=1.19e12, market_cap_as_of=date(2026, 10, 2)),
         B.happening_sentence("MU", price=PRICE, upcoming=dict(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2),
                                                               expiration=date(2026, 10, 17), avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25)))]
    b = [B.profile_sentence(short_description="Beta sells shoes.", sector="Retail", industry="Apparel", profile_as_of=date(2025, 4, 11), market_cap=23.4e9, market_cap_as_of=date(2025, 4, 9)),
         B.happening_sentence("ZZ", price=dict(quote_price=43.11, quote_ts=1744398000, last_close=41.77, last_close_date=date(2025, 4, 11), high_52w=66.6, high_52w_date=date(2025, 1, 3),
                                               anchor_close_3m=48.8, anchor_date_3m=date(2025, 1, 13)),
                              upcoming=dict(today=date(2025, 4, 14), next_date=date(2025, 4, 29), confirmation="estimated", source="x", timing="bmo", implied_pct=0.041, chain_date=date(2025, 4, 11),
                                            expiration=date(2025, 5, 8), avg_abs_1d=3.3, sample_n=36, sample_as_of=date(2025, 1, 29)))]
    for sa, sb in zip(a, b):
        assert sa and sb and sa["key"] == sb["key"]
        shared = numbers(sa["text"]) & numbers(sb["text"])
        assert shared <= numbers(sa["rule"]) | numbers(sb["rule"]), (sa["key"], shared)
        assert_receipted(sa); assert_receipted(sb)
    for t in [x["text"] for x in a + b]:
        assert not re.search(r"stored|yfinance|finnhub|the street|rv_rank|out of 100|_", t), t
    for const in (B.WINDOW_52W_DAYS, B.WINDOW_3M_DAYS, B.REACTION_WINDOW_SESSIONS, B.DESCRIPTION_SENTENCES):
        assert isinstance(const, int)


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
async def test_the_route_serves_the_two_blocks_receipted_and_the_home_block_reads_the_same_two():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/tickers/MU/briefing")).json()
        assert body["symbol"] == "MU" and [s["key"] for s in body["sentences"]] == ["profile", "happening"]
        for s in body["sentences"]:
            assert s["as_of"] and s["rule"] and s["inputs"]
            assert_receipted(s)
        assert (await c.get("/api/v1/tickers/ZZNOPE/briefing")).status_code == 404
        feat = (await c.get("/api/v1/discover/featured")).json()
        assert set(s["key"] for s in feat["sentences"]) <= {"profile", "happening"}
        if feat["symbol"]:
            assert feat["picked_on"] and feat["earnings_date"] and feat["rule"]


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
    assert move_from_bars(df, date(2026, 10, 2), "unknown") is None
