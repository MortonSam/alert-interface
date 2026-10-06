"""The Overview's two blocks from fixtures: every sentence-B branch and its omissions, the description cap, plain-words
market cap, no literal numbers in templates, no plumbing words in visible text, and the route."""
import re
from datetime import date, timedelta

import pytest

from app.services import briefing as B

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
    """Every number in the text is an input or a constant the rule names; no plumbing word is visible; the as-of is never ahead."""
    assert s["as_of"] is None or date.fromisoformat(s["as_of"]) <= date.today()
    missing = [n for n in numbers(s["text"]) if n not in receipts(s)]
    assert not missing, (missing, s["text"])
    assert not PLUMBING.search(s["text"]), s["text"]


# ── block 1 ──────────────────────────────────────────────────────────────────

def test_profile_quotes_the_first_sentence_then_the_gics_sentence_with_quote_times_shares():
    desc = "Micron Technology, Inc. designs, manufactures, and sells memory and storage products. The company operates through four segments: Compute, Mobile, Storage, and Embedded."
    s = B.profile_sentence(name="Micron Technology, Inc.", short_description=desc, profile_as_of=date(2026, 10, 5), gics_sector="Information Technology", gics_sub_industry="Semiconductors",
                           gics_as_of=date(2026, 10, 5), index_member=True, quote_price=1063.96, quote_ts=QUOTE_TS, shares_outstanding=1_119_000_000, shares_as_of=date(2026, 10, 5))
    assert s["text"] == ("Micron Technology, Inc. designs, manufactures, and sells memory and storage products. "
                         "It's part of the S&P 500's Information Technology sector (Semiconductors), worth about $1.2 trillion.")
    assert {"name": "GICS sector", "value": "Information Technology", "as_of": "2026-10-05", "source": "S&P 500 constituent list (tickers.sector), the same source Discover shows"} in s["inputs"]
    assert any(i["name"] == "shares outstanding" and i["value"] == "1,119.0 million" and i["as_of"] == "2026-10-05" for i in s["inputs"])
    assert any(i["name"] == "market cap" and i["value"] == "$1.2 trillion" and i["as_of"] == "Oct 5, 4:00 PM ET" for i in s["inputs"])
    assert any(i["name"] == "company name" and i["value"] == "Micron Technology" for i in s["inputs"])
    assert_clean(s)
    # no GICS data: the sector clause is omitted; no shares: no value; off the index: no S&P claim
    s = B.profile_sentence(name="Conagra Brands, Inc.", short_description="Conagra makes food.", profile_as_of=T, quote_price=20.0, quote_ts=QUOTE_TS)
    assert s["text"] == "Conagra makes food."
    s = B.profile_sentence(name="Conagra Brands, Inc.", short_description="Conagra makes food.", profile_as_of=T, gics_sector="Consumer Staples", gics_sub_industry="Packaged Foods & Meats", index_member=False)
    assert s["text"] == "Conagra makes food. It's in the Consumer Staples sector (Packaged Foods & Meats)."
    assert B.profile_sentence(name="X", gics_sector="Energy") is None                                       # no description, no block


def test_description_is_the_first_sentence_and_a_short_non_listing_second():
    assert B.description_text("Alpha Corp. makes glass. It sells it to builders.") == "Alpha Corp. makes glass. It sells it to builders."
    assert B.description_text("Alpha Corp. makes glass. The company operates through two segments, Flat and Auto.") == "Alpha Corp. makes glass."
    assert B.description_text("Alpha Corp. makes glass. Its Flat segment offers windows.") == "Alpha Corp. makes glass."
    assert B.description_text("Alpha Corp. makes glass. It sells windows, doors, mirrors, and panels.") == "Alpha Corp. makes glass."      # three commas: a listing
    long_first = "Alpha Corp. " + "makes glass for buildings and cars in many markets " * 3 + "worldwide."
    assert len(long_first) >= B.SECOND_SENTENCE_IF_FIRST_UNDER
    assert B.description_text(long_first + " It is based in Ohio.") == long_first                               # a long first sentence stands alone
    very_long = "Alpha Corp. " + "makes glass " * 60 + "worldwide."
    assert len(very_long) > B.DESCRIPTION_CAP and B.description_text(very_long + " It is based in Ohio.") == very_long   # never cut mid-sentence
    second_too_long = "Alpha makes glass. " + "It sells it in " + " and ".join(f"region {i}" for i in range(60)) + "."
    assert B.description_text(second_too_long) == "Alpha makes glass."                                            # the pair would breach the cap
    assert B.description_text("Beta Inc. sells shoes. The company was incorporated in 1998. It has 40 stores.") == "Beta Inc. sells shoes. It has 40 stores."
    assert B.description_text(None) is None and B.description_text("") is None
    assert B.split_sentences("Acme Corp. builds in the U.S. market. Second here. Third.") == ["Acme Corp. builds in the U.S. market.", "Second here.", "Third."]
    for name, short in (("Micron Technology, Inc.", "Micron Technology"), ("Constellation Brands, Inc.", "Constellation Brands"), ("Microsoft Corporation", "Microsoft"),
                        ("Fair Isaac Corporation", "Fair Isaac"), ("Conagra Brands Inc", "Conagra Brands"), ("Coca-Cola Co.", "Coca-Cola"), ("Linde plc", "Linde"), ("Co", "Co")):
        assert B.short_name(name) == short, name


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
    daily2 = list(daily); daily2[-10] = (daily2[-10][0], 3.0)                               # 3.75x: under the 4x threshold
    assert B.find_big_move(daily2, {daily[-3][0], daily[-2][0]}, T) is None


def test_branch_3_next_report_within_45_days_with_the_options_clause_only_on_a_fresh_chain():
    t, _, _ = B.upcoming_clause(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", note="confirmed: press release via Finnhub news 2026-09-10: Q4 date", source="finnhub",
                                timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2), avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25))
    assert t == "Reports Oct 14, 2026 after the close, 9 days away (confirmed by the company); options price a move of about ±8.7% against a typical ±6.3%."
    t, _, _ = B.upcoming_clause(today=T, next_date=date(2026, 10, 6), confirmation="estimated", source="yfinance", timing="bmo", avg_abs_1d=4.0, sample_n=8)
    assert t == "Reports Oct 6, 2026 before the open, 1 day away (estimated)."                  # no fresh chain: no options clause
    assert B.upcoming_clause(today=T, next_date=T, confirmation="expected_unconfirmed")[0] == "Reports Oct 5, 2026, today (expected, not confirmed)."


def test_sentence_b_priority_window_then_report_within_7_days_then_big_move_then_report_within_45():
    rep = dict(today=T, event_date=date(2026, 9, 30), timing="amc", eps_actual=3.03, eps_estimate=2.86, outcome="beat", pct_change_1d=3.0)
    big = dict(move_date=date(2026, 9, 25), move_pct=-9.1, typical_abs=1.3, multiple=7.0)
    soon = dict(today=T, next_date=date(2026, 10, 6), confirmation="estimated", source="yfinance", timing="amc")
    later = dict(today=T, next_date=date(2026, 10, 28), confirmation="estimated", source="yfinance", timing="amc")
    s = B.happening_sentence("MU", stock=STOCK, reported=rep, big_move=big, upcoming=soon)
    assert "Reported Sep 30, 2026" in s["text"] and "biggest move" not in s["text"] and "Reports" not in s["text"]        # 1: the window wins
    s = B.happening_sentence("STZ", stock=STOCK, big_move=big, upcoming=soon)
    assert s["text"].endswith("Reports Oct 6, 2026 after the close, 1 day away (estimated).") and "biggest move" not in s["text"]   # 2: a report within 7 days beats a big move
    s = B.happening_sentence("FICO", stock=STOCK, big_move=big, upcoming=later)
    assert "biggest move" in s["text"] and "Reports" not in s["text"]                                                   # 3: the big move beats a report 23 days out
    s = B.happening_sentence("MSFT", stock=STOCK, upcoming=later)
    assert s["text"].endswith("Reports Oct 28, 2026 after the close, 23 days away (estimated).")                        # 4: the report within 45 days
    assert s["as_of"] == "2026-10-05"                                                                                   # dated by the quote, not by the report ahead
    s = B.happening_sentence("MU", stock=STOCK, upcoming=dict(today=T, next_date=T + timedelta(days=B.NEXT_WITHIN_DAYS + 1)))
    assert s["text"] == B.stock_sentence("MU", **STOCK)[0]                                                              # beyond 45 days: sentence B omitted
    for x in (B.happening_sentence("MU", stock=STOCK, reported=rep), B.happening_sentence("STZ", stock=STOCK, big_move=big, upcoming=soon)):
        assert_clean(x)
    assert B.NEXT_SOON_DAYS == 7 and B.BIG_MOVE_MULTIPLE == 4
    assert B.happening_sentence("MU", stock=dict(quote_price=None, quote_ts=None)) is None
    assert B.happening_sentence("MU") is None


# ── nothing numeric lives in a template; no plumbing words ──────────────────

def test_no_number_in_a_block_is_a_literal_of_its_template():
    a = [B.profile_sentence(name="Alpha Inc.", short_description="Alpha makes chips.", gics_sector="Information Technology", gics_sub_industry="Semiconductors", gics_as_of=date(2026, 10, 5), index_member=True,
                            profile_as_of=date(2026, 10, 5), quote_price=187.52, quote_ts=QUOTE_TS, shares_outstanding=6_350_000_000, shares_as_of=date(2026, 10, 2)),
         B.happening_sentence("MU", stock=STOCK, upcoming=dict(today=T, next_date=date(2026, 10, 14), confirmation="confirmed", timing="amc", implied_pct=0.087, chain_date=date(2026, 10, 2),
                                                               avg_abs_1d=6.3, sample_n=20, sample_as_of=date(2026, 6, 25))),
         B.happening_sentence("MU", stock=STOCK, big_move=dict(move_date=date(2026, 9, 25), move_pct=-9.1, typical_abs=1.3, multiple=7.0))]
    b = [B.profile_sentence(name="Beta Corp.", short_description="Beta sells shoes.", gics_sector="Consumer Discretionary", gics_sub_industry="Footwear", gics_as_of=date(2025, 4, 11), index_member=False,
                            profile_as_of=date(2025, 4, 11), quote_price=43.11, quote_ts=1744398000, shares_outstanding=540_000_000, shares_as_of=date(2025, 4, 9)),
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
    for const in (B.WINDOW_52W_DAYS, B.WINDOW_3M_DAYS, B.REACTION_WINDOW_SESSIONS, B.DESCRIPTION_SENTENCES, B.DESCRIPTION_CAP, B.NEAR_HIGH_PCT, B.BIG_MOVE_SESSIONS, B.BIG_MOVE_MULTIPLE, B.NEXT_WITHIN_DAYS, B.NEXT_SOON_DAYS, B.SECOND_SENTENCE_IF_FIRST_UNDER, B.LISTING_COMMAS):
        assert isinstance(const, int)


# ── the route ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_route_serves_the_two_blocks_and_an_inactive_state():
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
        assert (await c.get("/api/v1/discover/featured")).status_code == 404                      # the featured block is gone


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


@pytest.mark.asyncio
async def test_a_reports_confirmation_reads_the_same_on_the_overview_and_on_discover():
    """One date can never read confirmed on one page and estimated on another: both read services.earnings_calendar.level_of
    on the same event row. STZ is the case that was questioned; any ticker with a report inside the Discover window works."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.services.earnings_calendar import level_of
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        soon = (await c.get("/api/v1/discover/reporting-soon?days=14")).json()           # the page's own window
        listed = soon if isinstance(soon, list) else next((v for v in soon.values() if isinstance(v, list)), [])
        rows = {i["symbol"]: i for i in listed if isinstance(i, dict) and "symbol" in i}
        sym = "STZ" if "STZ" in rows else next(iter(rows), None)
        if sym is None:
            pytest.skip("no report inside Discover's window locally")
        brief = (await c.get(f"/api/v1/tickers/{sym}/briefing")).json()
        by_symbol = (await c.get(f"/api/v1/tickers/by-symbol/{sym}")).json()
        happening = next((s for s in brief["sentences"] if s["key"] == "happening"), None)
        confidence = next((i["value"] for i in (happening or {}).get("inputs", []) if i["name"] == "confidence"), None)
        if confidence is None:
            pytest.skip(f"{sym}'s Overview is not on its next report today (another branch won)")
        assert confidence == rows[sym]["confirmation"] == by_symbol["next_earnings_confirmation"]
        assert B.confidence_phrase(confidence) in happening["text"]
        assert B.confidence_phrase(rows[sym]["confirmation"]) == B.confidence_phrase(confidence)
    # every level the shared function can return has a phrase on the Overview
    for level in ("confirmed", "estimated", "expected_unconfirmed"):
        assert B.confidence_phrase(level)
    assert level_of(True, None) == "confirmed" and level_of(False, None) == "estimated" and level_of(True, date(2026, 10, 1)) == "expected_unconfirmed"
