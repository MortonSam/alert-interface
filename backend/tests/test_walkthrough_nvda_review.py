"""Sam's NVDA walkthrough review (2026-10-29): the company's own explanations quoted with their checks, step 4 led by the industry
and no market verdict for a stock that is part of the market, P/E charts that never break and a P/E check that fits the company,
the next Fed decision chosen when served, and the options line beside the typical move. All pure."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.routers.walkthrough import gate
from app.services import walkthrough as W
from app.services import walkthrough_checks as C
from app.services import walkthrough_data as D
from app.services import walkthrough_quotes as Q

NY = ZoneInfo("America/New_York")


def _sessions(n: int, end: date) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _line(days: list[date], start: float, total_pct: float) -> list[tuple[date, float]]:
    return [(d, start * (1 + total_pct / 100) ** (i / (len(days) - 1))) for i, d in enumerate(days)]


# ── step 4 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _step4(share_pct: float | None):
    days = _sessions(300, date(2026, 10, 27))
    stock, spy = _line(days, 100, 25.0), _line(days, 100, 14.9)
    year = days[-253:]
    sec = {"members": 74, "change_1y": 24.1, "change_3m": 12.3, "index": [(d, 100.0 + i * 0.1) for i, d in enumerate(year)]}
    moves = [{"date": date(2026, 8, 27), "move_pct": 8.7, "spy_pct": 0.7, "owner": "company", "report_day": True}]
    share = {"pct": share_pct, "as_of": date(2026, 10, 20), "members": 503} if share_pct is not None else None
    stock = [(d, v) for d, v in stock[:-253]] + _line(year, 100, 17.3)
    spy = [(d, 100.0) for d in days[:-253]] + _line(year, 100, 14.9)
    return W.step_stock("NVIDIA", "Information Technology", stock, spy, sec, moves, 0.5, date(2026, 10, 28), share)


def test_step4_leads_with_the_industry_and_gives_a_stock_that_is_part_of_the_market_no_market_verdict():
    s = _step4(7.1)
    assert s["sentences"][0] == ("Over the past year NVIDIA's stock rose 17.3%, against a 24.1% rise for the median Information Technology stock in the S&P 500, "
                                 "so it lagged its industry.")
    assert s["sentences"][1] == "The S&P 500 rose 14.9% over the same year, and NVIDIA makes up 7.1% of the index by market value."
    shown = " ".join(s["sentences"] + [s["summary"]] + [d["as_of"] for d in s["deeper"]] + [s["check"]["question"], s["check"]["why"]])
    assert not re.search(r"\bmostly\b|the whole market|the market's|carried", shown)       # no market-or-company verdict, for the year or a day
    assert s["check"]["options"][s["check"]["answer"]] == C.INDEX_SHARE_RIGHT
    assert [n["label"] for n in s["numbers"]][:2] == ["NVIDIA over one year", "Median Information Technology stock over one year"]
    assert not any("Ivy calls two moves close" in d["label"] for d in s["deeper"])           # the rule's text left Go deeper
    assert W.INDEX_SHARE_NO_VERDICT == 2.0


def test_step4_for_a_smaller_stock_keeps_the_market_question_without_a_verdict_on_screen():
    s = _step4(1.4)
    assert "lagged" not in s["sentences"][0] and "for the S&P 500 itself" in s["sentences"][0]
    assert s["check"]["options"] == ["The company", "Its industry", "The whole market"]
    assert "so that move was mostly NVIDIA's own" in s["sentences"][-1]


def test_index_share_is_the_stored_market_value_over_the_index():
    t = lambda mc, member=True: {"market_cap": mc, "index_member": member, "market_cap_updated_at": datetime(2026, 10, 20, tzinfo=NY)}
    tickers = {"NVDA": t(5.25e12), "AAA": t(30e12), "BBB": t(38.65e12), "OUT": t(9e12, False)}
    assert W.index_share("NVDA", tickers) == {"pct": 7.1, "as_of": date(2026, 10, 20), "members": 3}
    assert W.index_share("OUT", tickers) is None
    assert W.industry_verdict(17.3, 24.1) == "lagged" and W.industry_verdict(30.0, 24.1) == "kept pace with" and W.industry_verdict(60.0, 24.1) == "outpaced"


# ── step 5 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _snap(pe=27.6, median=52.6):
    return {"status": "ok", "pe": pe, "as_of_date": date(2026, 10, 27), "window_end": date(2026, 7, 26), "hist_median": median, "trailing_eps": 7.91,
            "hist_sessions": 1060, "hist_first": date(2021, 10, 25), "hist_last": date(2026, 10, 27), "price": 217.9}


def test_a_pe_chart_never_breaks_and_says_where_it_starts():
    first = [(d, 60.0) for d in _sessions(300, date(2023, 2, 22))]
    second = [(d, 40.0 + (i % 30)) for i, d in enumerate(_sessions(760, date(2026, 10, 27)))]
    series = first + second
    left = {d: "over_cap" for d in _sessions(150, date(2023, 9, 20))[:140] if d > date(2023, 2, 22)}
    med = round(sorted(v for _, v in series)[len(series) // 2], 1)
    s = W.step_valuation("NVIDIA", "Information Technology", _snap(median=med), series, None, True, None, left)
    assert s["chart"] and W.chart_gaps(s["chart"]) == []
    assert s["chart"]["start"] == second[0][0].isoformat() and s["chart"]["points"][0][0] == second[0][0].isoformat()
    assert f"The chart starts on {W.fmt_date(second[0][0])}. Before that, investors paid more than $100 for each $1 of its profit at times" in s["sentences"][-1]
    assert "Its five-year range" in [n["label"] for n in s["numbers"]]                       # the range stays the history's


def test_a_short_break_widened_by_sampling_still_draws_no_gap():
    days = _sessions(900, date(2026, 10, 27))
    series = [(d, 30.0) for i, d in enumerate(days) if not 600 <= i < 612]          # a 12-session break: under the limit daily, over it sampled
    s = W.step_valuation("X", "Industrials", _snap(pe=30.0, median=30.0), series, None, True)
    assert s["chart"] and W.chart_gaps(s["chart"]) == []


def test_no_walkthrough_chart_ever_has_a_gap():
    assert W.chart_gaps({"kind": "pe_range", "points": [["2026-01-02", 1], ["2026-02-02", 1]]}) == ["pe_range pe: 2026-01-02 to 2026-02-02"]
    assert W.chart_gaps(_step4(7.1)["chart"]) == []
    for gap_at in (5, 200, 700):                                                              # a hole anywhere: the chart shows the latest unbroken run
        days = _sessions(1000, date(2026, 10, 27))
        series = [(d, 30.0) for i, d in enumerate(days) if not gap_at <= i < gap_at + 30]
        s = W.step_valuation("X", "Industrials", _snap(pe=30.0, median=30.0), series, None, True)
        assert s["chart"] and W.chart_gaps(s["chart"]) == [], gap_at
    axis = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "walkthroughAxis.ts"
    if axis.exists():                                                                         # the frontend breaks a line at the same width
        assert f"GAP_DAYS = {W.CHART_GAP_DAYS};" in axis.read_text()


def test_the_pe_left_out_reasons():
    q = lambda end, eps, filed: {"end": end, "start": end - timedelta(days=90), "eps": eps, "filed": filed}
    quarters = [q(date(2023, 1, 1), -1.0, date(2023, 2, 1)), q(date(2023, 4, 1), 0.1, date(2023, 5, 1)), q(date(2023, 7, 1), 0.1, date(2023, 8, 1)),
                q(date(2023, 10, 1), 0.2, date(2023, 11, 1)), q(date(2024, 1, 1), 3.0, date(2024, 2, 1))]
    bars = [(date(2023, 11, 15), 100.0), (date(2024, 2, 15), 100.0)]
    assert D.pe_left_out(bars, quarters, []) == {date(2023, 11, 15): "loss"}
    assert D.pe_left_out([(date(2024, 2, 15), 400.0)], quarters, []) == {date(2024, 2, 15): "over_cap"}


def test_the_pe_check_fits_the_company_nvidia_whose_profits_grew_faster_than_its_price():
    year = {"eps_pct": 125.4, "price_pct": 17.3, "pe_then": 54.2, "now": date(2026, 10, 27)}
    c = C.pe_check("NVIDIA", 27.6, 52.6, year)
    assert c["options"][c["answer"]] == "Its profits grew faster than its price"
    assert "They expect its profits to fall from here" not in c["options"]
    assert "earnings per share over four quarters rose 125.4% while its share price rose 17.3%" in c["why"] and "a year earlier they paid $54" in c["why"]
    # already below its median a year earlier: the year is not why, the usual reading stands
    assert C.pe_check("NVIDIA", 27.6, 52.6, {**year, "pe_then": 30.0})["options"][C.pe_check("NVIDIA", 27.6, 52.6, {**year, "pe_then": 30.0})["answer"]] == C.PE_RIGHT["below"]
    up = C.pe_check("X", 40.0, 25.0, {"eps_pct": 2.0, "price_pct": 60.0, "pe_then": 25.0, "now": date(2026, 10, 27)})
    assert up["options"][up["answer"]] == "Its price rose faster than its profits"
    assert C.pe_check("X", 27.6, 52.6, None)["options"][C.pe_check("X", 27.6, 52.6, None)["answer"]] == C.PE_RIGHT["below"]


def test_the_year_behind_a_pe():
    q = lambda end, eps: {"end": end, "start": end - timedelta(days=90), "eps": eps, "filed": end + timedelta(days=30)}
    ends = [date(2024, 10, 27), date(2025, 1, 26), date(2025, 4, 27), date(2025, 7, 27), date(2025, 10, 26), date(2026, 1, 25), date(2026, 4, 26), date(2026, 7, 26)]
    quarters = [q(e, v) for e, v in zip(ends, [0.78, 0.89, 0.76, 1.08, 1.30, 1.76, 2.39, 2.46])]
    bars = [(date(2025, 10, 27), 191.0), (date(2026, 10, 27), 217.9)]
    y = D.pe_year(bars, quarters, _snap())
    assert y["eps_pct"] == round((7.91 / 3.51 - 1) * 100, 1) and y["price_pct"] == round((217.9 / 191.0 - 1) * 100, 1) and y["pe_then"] == round(191.0 / 3.51, 1)


# ── step 6 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_next_fed_decision_is_never_in_the_past():
    from app.services.fomc_calendar import decision_days
    assert W.next_fed_day(datetime(2026, 10, 28, 10, 0, tzinfo=NY)) == date(2026, 10, 28)
    assert W.next_fed_day(datetime(2026, 10, 28, 14, 0, tzinfo=NY)) == date(2026, 12, 9)        # after the 2pm statement
    assert W.next_fed_day(datetime(2026, 10, 29, 9, 0, tzinfo=NY)) == date(2026, 12, 9)
    d = datetime(2026, 1, 1, 9, tzinfo=NY)
    while d.year < 2028:
        nxt = W.next_fed_day(d)
        assert nxt is None or nxt >= d.date(), d
        assert nxt is None or nxt == min(x for x in decision_days(d.date()) if x > d.date() or (x == d.date() and d.hour < 14))
        d += timedelta(hours=11)


def test_a_stored_walkthrough_shows_the_next_fed_decision_as_served():
    ne = SimpleNamespace(date=date(2026, 11, 17), confirmation="confirmed", window_start=None, window_end=None, note=None)
    s6 = W.step_upcoming("NVIDIA", ne, "amc", None, {"pct": 6.6, "n": 20, "as_of": date(2026, 8, 26)}, date(2026, 10, 28), 1.8)
    assert "The next Fed rate decision is on Wed, Oct 28, 2026, a day that can move the whole market." in s6["sentences"]  # as the Oct 28 build wrote it
    steps = [{"key": k, "status": "absent", "point": None, "summary": None, "gap": None, "idea": None, "check": None, "n": i + 1}
             for i, k in enumerate(W.KEYS.values()) if k != "upcoming"]
    steps.insert(5, s6)
    payload = {"name": "NVIDIA", "steps": steps, "compare": {"rows": {}}, "noun": "sales"}
    out = gate(payload, True, True, now=datetime(2026, 10, 29, 9, 0, tzinfo=NY))
    up = next(s for s in out["steps"] if s["key"] == "upcoming")
    fed = [x for x in up["sentences"] if x.startswith("The next Fed")]
    assert fed == ["The next Fed rate decision is on Wed, Dec 9, 2026, a day that can move the whole market."]
    assert [d["value"] for d in up["deeper"] if d["label"] == W.FED_LABEL] == ["Wed, Dec 9, 2026"]


def test_the_options_line_compares_like_with_like():
    """Sam's NVDA review (2026-11-02): a move through an expiration is never set beside the typical report-day move. With a confirmed
    date and the report's own share of the move on file, that share is compared; otherwise the figure is stated with its expiration
    and compared with nothing."""
    typical = {"pct": 6.6, "n": 20, "as_of": date(2026, 8, 26)}
    imp = {"pct": 7.4, "chain_date": date(2026, 10, 28), "expiration": date(2026, 11, 20)}
    ne = SimpleNamespace(date=date(2026, 11, 17), confirmation="confirmed", window_start=None, window_end=None, note=None)
    # the report's own share on file: it is the figure, compared by the site's one rule
    share = {"pct": 5.1, "chain_date": date(2026, 10, 28), "verdict": "less than usual"}
    s = W.step_upcoming("NVIDIA", ne, "amc", imp, typical, None, 1.8, share)
    assert "After its past 20 reports, the stock moved ±6.6% on a typical report day." in s["sentences"]
    assert "Options price a move of about ±5.1% from the report itself, less than its typical move on a report day." in s["sentences"]
    assert not any("by Nov 20" in x for x in s["sentences"])
    assert [n["label"] for n in s["numbers"]] == ["Next report", "Typical move after a report", "Options price for the report itself"]
    # no share: the move through the expiration, with its date, beside nothing
    s = W.step_upcoming("NVIDIA", ne, "amc", imp, typical, None, 1.8, None)
    assert "Options price a move of about ±7.4% by Nov 20, 2026, the first expiration after the report." in s["sentences"]
    assert not any(w in " ".join(s["sentences"]) for w in ("more than its typical", "less than its typical", "about the same as"))
    # a share whose comparison the rule withholds (too few reports): stated alone
    s = W.step_upcoming("NVIDIA", ne, "amc", imp, typical, None, 1.8, {**share, "verdict": None})
    assert "Options price a move of about ±5.1% from the report itself." in s["sentences"]
    est = SimpleNamespace(date=date(2026, 11, 17), confirmation="estimated", window_start=None, window_end=None, note=None)
    assert not any("Options price" in x for x in W.step_upcoming("NVIDIA", est, None, imp, typical, None, 1.8, share)["sentences"])


def test_realty_income_nov_2_report_with_the_nov_20_expiration_makes_no_comparison():
    """O: reports Nov 2, the first expiration after it is Nov 20, eighteen days on; with no report share on file the straddle to
    Nov 20 is stated as a move by Nov 20 and never against the ±1.9% report-day move."""
    typical = {"pct": 1.9, "n": 20, "as_of": date(2026, 8, 5)}
    ne = SimpleNamespace(date=date(2026, 11, 2), confirmation="confirmed", window_start=None, window_end=None, note=None)
    imp = {"pct": 3.2, "chain_date": date(2026, 10, 30), "expiration": date(2026, 11, 20)}
    s = W.step_upcoming("Realty Income", ne, "amc", imp, typical, None, 0.6, None)
    line = [x for x in s["sentences"] if x.startswith("Options price")]
    assert line == ["Options price a move of about ±3.2% by Nov 20, 2026, the first expiration after the report."]
    assert "typical" not in line[0]


# ── the company's own words ────────────────────────────────────────────────────────────────────────────────────────────────

SOURCES = {
    "periodic": {"form": "10-Q", "accession": "0001045810-26-000100", "filed": "2026-08-26", "document": "nvda-20260726.htm",
                 "url": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000100/nvda-20260726.htm",
                 "paragraphs": ["Revenue for the second quarter of fiscal year 2027 was $96.2 billion, up 106% from a year ago. Data Center revenue was up 112% "
                                "driven by demand for our Blackwell computing platform.",
                                "Gross margin increased to 75.1% from 72.4% a year ago, primarily due to a higher mix of Data Center products."]},
    "release": {"form": "8-K", "accession": "0001045810-26-000098", "filed": "2026-08-26", "document": "q2fy27pr.htm",
                "url": "https://www.sec.gov/x", "paragraphs": ["Revenue is expected to be $110.0 billion, plus or minus 2%."]},
}
WANT = {"growth": {"noun": "sales", "direction": "rose", "period": "fiscal Q2 2027", "end": "2026-07-26", "measure_words": "sales"},
        "margins": {"measure": "gross", "measure_words": "gross margin", "end": "2026-07-26", "noun": "sales"},
        "outlook": {"measure_words": "an expectation", "noun": "sales"}}


def test_a_quote_must_be_the_companys_own_words_and_a_reason():
    good = "Data Center revenue was up 112% driven by demand for our Blackwell computing platform."
    assert Q.quote_problems("growth", WANT["growth"], good, "M1", SOURCES) == []
    assert "is not copied word for word from M1" in Q.quote_problems("growth", WANT["growth"], "Data Center revenue soared on Blackwell demand.", "M1", SOURCES)
    assert "states no reason for the change" in Q.quote_problems("growth", WANT["growth"],
                                                                "Revenue for the second quarter of fiscal year 2027 was $96.2 billion, up 106% from a year ago.", "M1", SOURCES)
    assert Q.quote_problems("margins", WANT["margins"], "Gross margin increased to 75.1% from 72.4% a year ago, primarily due to a higher mix of Data Center products.",
                            "M2", SOURCES) == []
    assert "does not name gross margin" in Q.quote_problems("margins", WANT["margins"], good, "M1", SOURCES)
    assert Q.quote_problems("outlook", WANT["outlook"], "Revenue is expected to be $110.0 billion, plus or minus 2%.", "R1", SOURCES) == []
    assert "an outlook must come from its latest earnings release" in Q.quote_problems("outlook", WANT["outlook"], good, "M1", SOURCES)
    newer = {**SOURCES, "last_release": {**SOURCES["release"], "accession": "0001045810-26-000200", "paragraphs": ["Revenue is expected to be $120 billion."]}}
    assert "an outlook must come from its latest earnings release" in Q.quote_problems("outlook", WANT["outlook"], "Revenue is expected to be $110.0 billion, plus or minus 2%.", "R1", newer)
    assert Q.quote_problems("growth", WANT["growth"], good, "M9", SOURCES) == ["names no paragraph it was copied from (M9)"]
    o = "We delivered another quarter of solid AFFO per share growth. As a result, we raise our 2026 AFFO per share guidance to $4.44 - $4.45."
    assert "a sentence of it states no expectation (an outlook quote is the outlook alone)" in Q.quote_problems(
        "outlook", WANT["outlook"], o, "R1", {**SOURCES, "release": {**SOURCES["release"], "paragraphs": [o]}})
    seq = "Total revenue for the third quarter of 2026 increased 74% as compared to the second quarter of 2026, primarily due to increases in sales of DRAM."
    assert "compares with the quarter before, not a year earlier" in Q.quote_problems("growth", WANT["growth"], seq, "M1", {**SOURCES, "periodic": {**SOURCES["periodic"], "paragraphs": [seq]}})
    yoy = "Total revenue for the third quarter of 2026 increased 346% as compared to the third quarter of 2025, primarily due to increases in sales of DRAM."
    assert not Q.sequential_only(yoy) and Q.sequential_only(seq) and Q.sequential_only("Revenue rose 18% sequentially, driven by Blackwell.")
    assert not Q.sequential_only("Revenue was up 117% from a year ago and up 18% sequentially, driven by Blackwell.")
    assert Q.starts_a_sentence("Outlook for the third quarter: Revenue is expected to be $108.0 billion.", "Revenue is expected to be $108.0 billion.")
    assert Q.starts_a_sentence("• Revenue is expected to be $108.0 billion.", "Revenue is expected to be $108.0 billion.")
    o2 = "As a result, we are pleased to raise our 2026 AFFO per share guidance to $4.44 - $4.45."
    assert "starts partway through a sentence" in Q.quote_problems("outlook", WANT["outlook"], o2[12:], "R1", {**SOURCES, "release": {**SOURCES["release"], "paragraphs": [o2]}})
    assert Q.quote_problems("outlook", WANT["outlook"], o2, "R1", {**SOURCES, "release": {**SOURCES["release"], "paragraphs": [o2]}}) == []
    long = " ".join(["Revenue grew driven by demand."] * 3)
    assert any("sentences" in p or "words" in p for p in Q.quote_problems("growth", WANT["growth"], long, "M1", {**SOURCES, "periodic": {**SOURCES["periodic"], "paragraphs": [long]}}))


def test_a_verified_quote_shows_with_its_filing_and_a_rule_built_lead():
    stored = {"want": WANT, "quotes": {"growth": {"quote": "Data Center revenue was up 112% driven by demand for our Blackwell computing platform.", "paragraph": "M1",
                                                 "receipt": {k: SOURCES["periodic"][k] for k in ("form", "accession", "filed", "document", "url")}},
                                       "outlook": {"quote": "Revenue is expected to be $110.0 billion, plus or minus 2%.", "paragraph": "R1",
                                                  "receipt": {k: SOURCES["release"][k] for k in ("form", "accession", "filed", "document", "url")}}}}
    steps = [{"key": k, "status": "ok"} for k in W.KEYS.values()]
    payload = {"name": "NVIDIA", "steps": steps}
    Q.apply(payload, stored)
    g, up, m = steps[1]["quote"], steps[5]["quote"], steps[2].get("quote")
    assert g["lead"] == "How NVIDIA explains its sales in fiscal Q2 2027, in its 10-Q filed Aug 26, 2026" and g["source"]["label"] == "10-Q filed Aug 26, 2026"
    assert up["lead"] == "What NVIDIA said to expect, in its earnings release of Aug 26, 2026" and up["source"]["label"] == "Earnings release of Aug 26, 2026"
    assert m is None                                                                          # no verified quote: the step shows none, nothing written
    assert ":" not in g["lead"] + up["lead"]


def test_the_candidate_paragraphs_and_the_prompt():
    cands = Q.candidates(SOURCES, WANT)
    assert [i for i, _ in cands] == ["M1", "M2", "R1"]
    p = Q.build_prompt("NVIDIA", WANT, cands)
    assert "never write or change a word" in p and "copied exactly from ONE paragraph" in p
    assert Q.parse_picks('{"growth": {"paragraph": "M1", "quote": "x  y"}, "margins": null}', WANT) == {"growth": {"paragraph": "M1", "quote": "x y"}}


@pytest.mark.asyncio
async def test_a_quote_the_verifier_rejects_twice_is_dropped():
    calls = []

    class Fake:
        async def generate_walkthrough(self, prompt, max_tokens=900):
            calls.append("gen")
            return {"content": '{"growth": {"paragraph": "M1", "quote": "Data Center revenue was up 112% driven by demand for our Blackwell computing platform."}}',
                    "model_used": "claude-sonnet-4-5", "input_tokens": 10, "output_tokens": 10}

        async def verify_walkthrough(self, prompt):
            calls.append("ver")
            return {"content": '{"verdicts": [{"id": "growth", "status": "unsupported", "reason": "another quarter"}]}', "model_used": "claude-opus-4-1",
                    "input_tokens": 10, "output_tokens": 10}
    got = await Q.quotes_for("NVIDIA", {"growth": WANT["growth"]}, SOURCES, client=Fake())
    assert got["quotes"] == {} and calls == ["gen", "ver", "gen", "ver"] and got["dropped"] == [{"id": "growth", "reason": "another quarter"}]


def test_one_quarter_across_the_steps():
    """MU (Sam's review, 2026-11-02): step 2 showed fiscal Q3 2026 beside step 3 through fiscal Q4. A quarter step whose figure is for an
    earlier quarter than the latest reported keeps its figure, labelled with its period, and says the newer quarter's figure is not on
    file yet (Sam, 2026-11-10: JPM's steps 2 and 5 had gone blank); it never blanks."""
    def ok(n):
        return W._step(n, status="ok", numbers=[W._num("x", "1", "y")], sentences=["s"], idea={2: "growth", 3: "margins", 5: "pe"}[n])
    steps = [W._step(1, status="ok", idea="segments"), ok(2), ok(3), W._step(4, status="ok", idea="market_vs_company"), ok(5),
             W._step(6, status="ok", idea="report_move"), W._step(7, status="ok", idea="risk_factors")]
    q3, q4 = date(2026, 5, 28), date(2026, 9, 3)
    marked = W.one_quarter(steps, {2: q3, 3: q4, 5: date(2026, 8, 28)}, q4, None, "Micron")
    assert marked == [2]                                                    # Aug 28 and Sep 3 are the same quarter; May 28 is not
    assert steps[1]["status"] == "partial" and steps[1]["numbers"] == [W._num("x", "1", "y")]
    assert steps[1]["sentences"][-1] == ("Its revenue growth for the quarter ended Sep 3, 2026 isn't on file yet; the figures above are for "
                                         "the quarter ended May 28, 2026.")
    assert "shows no older quarter" not in str(steps)
    assert steps[1]["behind"] == {"end": "2026-05-28", "latest": "2026-09-03"}
    assert steps[2]["status"] == "ok" and steps[4]["status"] == "ok"
    assert W.one_quarter(steps, {2: q4}, None, None, "X") == []             # no reported quarter known: nothing changes


def test_no_step_blanks_while_its_figures_are_on_file_and_an_unreported_quarter_never_counts():
    """Sam, 2026-11-10: the walkthrough's quarter is the latest the company has reported (NVIDIA's quarter ended Oct 26, reported Nov 17,
    is not it on Nov 10), and no quarter step with figures on file ever goes blank, whatever the quarter."""
    assert W.reported_quarter([date(2026, 7, 26), date(2026, 10, 26)], date(2026, 8, 26)) == date(2026, 7, 26)
    assert W.reported_quarter([date(2026, 7, 26)], None) == date(2026, 7, 26) and W.reported_quarter([None], None) is None
    for latest in (date(2026, 9, 30), date(2027, 3, 31), date(2028, 6, 30)):
        steps = [W._step(n, status="ok", numbers=[W._num("x", "1", "y")], sentences=["s"],
                         idea={1: "segments", 2: "growth", 3: "margins", 4: "market_vs_company", 5: "pe", 6: "report_move", 7: "risk_factors"}[n])
                 for n in range(1, 8)]
        W.one_quarter(steps, {2: date(2026, 6, 30), 3: date(2025, 12, 31), 5: date(2026, 3, 31)}, latest, None, "X")
        assert all(s["status"] != "absent" and s["numbers"] for s in steps), [s["status"] for s in steps]
