"""Ivy's Read in plain English (services/ivy_read_plain): the page's facts, the rules, the band check and the write loop."""
import asyncio
import json
import re

from app.services import ivy_read_plain as P

# NVDA as production showed it on 2026-10-22: Details ±8.9% / $19.65 by Nov 20, about 4.4% from the Nov 17 report, typical 6.5%
# over 21 reports ("less than usual"), spread +8.8 points (the row: about the same), RV rank 11.4 (quiet)
NVDA_VALUES = {"expected_move_pct": 0.0886, "expected_move_dollars": 19.65, "expiration_used": "2026-11-20", "chain_date": "2026-10-21",
               "iv_rv_spread_pp": 8.8, "rv_rank": 11.4, "rv_percentile": 4.4, "next_earnings_date": "2026-11-17"}
NVDA_REPORT = {"report_move_state": "ok", "report_move_pct": 0.044, "report_move": {"report_date": "2026-11-17"},
               "typical_move_pct": 6.5, "typical_n": 21, "move_comparison": "less than usual", "report_confirmed": True}
NVDA = P.page_facts(symbol="NVDA", name="NVIDIA Corporation", fact_values=NVDA_VALUES, report=NVDA_REPORT)
OLD_NVDA = ("The market is pricing an implied move of ±8.9% (±$19.65) into the Nov 20, 2026 expiration, implying a range of $202.32 - "
            "$241.62 off a current price of $221.97. With 20-day realized vol sitting at just 25.1%, an RV rank of 11.4, and an IV-RV spread "
            "of +8.8pp, implied vol at 33.9% looks historically rich relative to what the stock has recently delivered, giving premium "
            "sellers a statistical edge on current conditions.")
GOOD = ("Options on NVIDIA price a move of ±8.9% ($19.65) by Nov 20, 2026. About 4.4% of that move comes from the report on Nov 17, 2026, "
        "less than its typical first-day move of 6.5% over 21 reports. Options expect about the same swing as the stock has "
        "shown lately. Lately it has been calmer than usual compared with its past year.")


def test_the_facts_and_band_words_are_the_pages_own():
    assert NVDA["spread_word"] == "about the same" and NVDA["swing_band"] == "quiet" and NVDA["lately"] == "calmer than usual"
    lines = P.fact_lines(NVDA)
    assert NVDA["name"] == "NVIDIA"                       # the page's short name (briefing.short_name)
    assert lines["A"] == "Options price a move of ±8.9% ($19.65) by Nov 20, 2026."
    # Sam (2026-10-26 evening): Sherwin-Williams' form, ending with the page's comparison word against the typical first-day move
    assert lines["B"] == "About 4.4% of that move comes from the report on Nov 17, 2026, less than its typical first-day move of 6.5% over 21 reports."
    assert "C" not in lines and "S" not in lines
    assert lines["D"] == "Lately it has been calmer than usual compared with its past year."
    assert lines["E"] == "Options expect about the same swing as the stock has shown lately."
    assert P.fact_lines({**NVDA, "spread_pp": 82.7, "spread_word": "pricey"})["E"] == "Options expect more swing than the stock has shown lately."
    assert P.fact_lines({**NVDA, "spread_pp": -12.0, "spread_word": "cheap"})["E"] == "Options expect less swing than the stock has shown lately."
    # the report share only on a company-confirmed date (Sam, 2026-10-26); the typical move then comes from the Details line
    vendor = P.page_facts(symbol="NVDA", name="NVIDIA Corporation", fact_values={**NVDA_VALUES, "avg_earnings_1d_move_pct": 6.6, "earnings_sample_size": 20},
                          report={**NVDA_REPORT, "report_confirmed": False})
    assert set(P.fact_lines(vendor)) == {"A", "S", "C", "D", "E"}
    assert P.fact_lines(vendor)["S"] == "That covers every trading day until then, not just the report day."
    assert P.fact_lines(vendor)["C"] == "On its past report days the stock has moved 6.6% on the first day on average, over 20 reports."
    assert P.page_facts(symbol="O", name="Realty Income Corporation", fact_values=NVDA_VALUES, report=None)["name"] == "Realty Income"
    assert P.page_facts(symbol="JPM", name="JPMorgan Chase & Co.", fact_values=NVDA_VALUES, report=None)["name"] == "JPMorgan Chase"
    # the security master's trailing "(The)" (GS failed every round on 2026-10-26: "Goldman Sachs Group Inc. (The)" split its first sentence)
    from app.services.briefing import short_name
    assert [short_name(n) for n in ("Goldman Sachs Group, Inc. (The)", "Coca-Cola Company (The)", "Procter & Gamble Company (The)",
                                     "Kimco Realty Corporation (HC)", "Southern Company (The)")] == \
        ["Goldman Sachs", "Coca-Cola", "Procter & Gamble", "Kimco Realty", "Southern"]
    assert P.spread_word(10.1) == "pricey" and P.spread_word(10.0) == "about the same" and P.spread_word(-10.1) == "cheap"
    # the band is the percentile's, like the page's row (MRNA, Oct 23: rank 19.6 but more than on 90% of days)
    mrna = P.page_facts(symbol="MRNA", name="Moderna", fact_values={**NVDA_VALUES, "rv_rank": 19.6, "rv_percentile": 90.9}, report=None)
    assert mrna["swing_band"] == "extreme" and mrna["lately"] == "much busier than usual"
    assert P.page_facts(symbol="X", name="X", fact_values={**NVDA_VALUES, "rv_rank": None}, report=None)["swing_band"] is None
    no_report = P.page_facts(symbol="X", name="X", fact_values=NVDA_VALUES, report={"report_move_state": "not_separated"})   # no typical in its values
    assert set(P.fact_lines(no_report)) == {"A", "S", "D", "E"}
    prompt = P.build_prompt(NVDA)
    assert "never traded options" in prompt and lines["A"] in prompt and "Never use: IV, RV" in prompt


def test_the_old_trader_note_breaks_the_rules():
    problems = P.read_problems(OLD_NVDA, NVDA)
    for expected in ['it uses "RV" without', 'it uses "pp" without', 'it uses "vol" without', 'it uses "premium" without',
                     "it mentions edge", "it mentions buyers or sellers", "it states figures the page's facts do not",
                     "it calls options pricey where the page says they expect about the same swing"]:
        assert any(p.startswith(expected) for p in problems), (expected, problems)


def test_a_plain_read_passes():
    assert P.read_problems(GOOD, NVDA) == []


def test_the_band_check_catches_each_contradiction():
    assert P.band_contradictions("Options look expensive next to recent swings.", NVDA)
    assert P.band_contradictions("The stock has been busier than usual lately.", NVDA)
    assert P.band_contradictions("About 4.4% is the report, more than the 6.5% it moves on a typical report.", NVDA)
    pricey = {**NVDA, "spread_word": "pricey"}
    assert P.band_contradictions("Options look cheap.", pricey) and not P.band_contradictions("Options look pricey.", pricey)
    busy = {**NVDA, "swing_band": "elevated"}
    assert P.band_contradictions("The stock has been calmer than usual.", busy)
    assert P.band_contradictions(GOOD, NVDA) == []
    # a negated band word asserts nothing (production's NTAP and ORCL reads, 2026-10-22)
    assert P.band_contradictions("Premium looks neither materially cheap nor rich from either side.", NVDA) == []
    assert P.band_contradictions("An RV rank of 37.9 keeps realized vol far from extreme.", NVDA) == []


def test_order_length_and_advice_rules():
    assert any("does not lead" in p for p in P.read_problems("Lately the stock has been calmer than usual. " + GOOD, NVDA))
    assert any("sentences, more than" in p for p in P.read_problems(GOOD + " It is a large company. It makes chips.", NVDA))
    assert any("mentions advice" in p for p in P.read_problems(GOOD.replace("Lately", "You should know that lately"), NVDA))
    assert any("month in full" in p for p in P.read_problems(GOOD.replace("Nov 20, 2026", "November 20, 2026"), NVDA))
    assert any("where its facts come from" in p for p in P.read_problems(GOOD.replace("Lately", "The page says lately"), NVDA))
    assert any("leaves out the typical" in p for p in P.read_problems(GOOD.replace(", less than its typical first-day move of 6.5% over 21 reports", ""), NVDA))
    assert any("line B" in p for p in P.read_problems(GOOD.replace("less than its typical first-day move of 6.5% over 21 reports", "while it has moved 6.5% over 21 reports"), NVDA))
    assert any("not line D" in p for p in P.read_problems(GOOD.replace("Lately it has been calmer than usual compared with its past year", "Lately the stock has been calmer than usual for it"), NVDA))
    assert any("line E" in p for p in P.read_problems(GOOD.replace(" Options expect about the same swing as the stock has shown lately.", ""), NVDA))
    assert any('call the company "NVIDIA"' in p for p in P.read_problems(GOOD.replace("on NVIDIA", "on NVIDIA Corporation").replace("NVIDIA Corporation", "Nvidia Corp"), NVDA))


def test_restating_clauses_are_banned():
    # Sam, 2026-10-26: "meaning...", "in either direction", "no indication whether up or down" (MU, STX, SHW and MRNA's Oct 26 drafts)
    for clause in (", meaning the market expects a swing of that size in either direction by that date", ", in either direction",
                   ", and that move could go in either direction", ", with no indication from the market whether that move would be up or down"):
        bad = GOOD.replace(" by Nov 20, 2026.", f" by Nov 20, 2026{clause}.", 1)
        assert any("restates the move" in p for p in P.read_problems(bad, NVDA)), clause
    explained = GOOD.replace("Lately the stock", "Its realized volatility, how much it has actually swung, shows the stock")
    assert not any('"volatility"' in p for p in P.read_problems(explained, NVDA))


class FakeClient:
    def __init__(self, drafts, verdict="supported"):
        self.drafts, self.verdict = list(drafts), verdict

    async def generate_options_read(self, prompt):
        return {"content": self.drafts.pop(0), "model_used": "claude-sonnet-5-5", "input_tokens": 10, "output_tokens": 10}

    async def verify_research_note(self, prompt):
        n = len(re.findall(r"^s\d+: ", prompt, re.M))
        rows = [{"id": f"s{i}", "status": self.verdict, "reason": "x"} for i in range(1, n + 1)]
        return {"content": json.dumps({"verdicts": rows}), "model_used": "claude-opus-5-5", "input_tokens": 10, "output_tokens": 10}


def test_write_read_rewrites_then_passes_or_serves_nothing():
    ok = asyncio.run(P.write_read(NVDA, client=FakeClient([OLD_NVDA, GOOD])))
    assert ok["result"] == "passed" and ok["content"] == GOOD and ok["attempts"] == 2
    bad = asyncio.run(P.write_read(NVDA, client=FakeClient([OLD_NVDA] * P.ROUNDS)))
    assert bad["result"] == "failed" and bad["content"] is None and bad["problems"]
    unverified = asyncio.run(P.write_read(NVDA, client=FakeClient([GOOD] * P.ROUNDS, verdict="unsupported")))
    assert unverified["result"] == "failed" and unverified["problems"][0].startswith("sentence 1 is unsupported")


def test_no_sentence_restates_an_earlier_one():
    # the Oct 26 draft for NVDA: sentence 2 only restated sentence 1
    filler = ("Options on NVIDIA are pricing in a move of \u00b18.9% ($19.65) by Nov 20, 2026. That percentage covers both upward "
              "and downward movement from the current price, so it describes a symmetric range rather than a directional forecast. "
              "Lately it has been calmer than usual compared with its past year.")
    no_report = {**NVDA, "report_pct": None, "typical_pct": None, "comparison": None, "span": None}
    assert P.restatements(filler, no_report) == [2]
    assert any("sentence 2 restates" in p for p in P.read_problems(filler, no_report))
    assert P.restatements(GOOD, NVDA) == []
    assert P.lines_stated("About 4.4% of that move comes from the report on Nov 17, 2026, less than its typical first-day move of 6.5% over 21 reports.", NVDA) == {"B", "C"}
    assert P.lines_stated("That covers every trading day until then, not just the report day.", NVDA) == {"S"}
    assert P.lines_stated("Options expect about the same swing as the stock has shown lately.", NVDA) == {"E"}
    assert P.lines_stated("Options expect more swing than the stock has shown lately.", NVDA) == {"E"}


def test_no_expected_move_means_no_read_and_no_model_call():
    cms = {**NVDA, "total_pct": None, "total_dollars": None}
    r = asyncio.run(P.write_read(cms, client=FakeClient([])))       # the fake has no drafts: any call would fail
    assert r["result"] == "no_move" and r["content"] is None and r["attempts"] == 0


def test_the_span_sentence_when_the_move_is_not_the_reports_alone():
    # Sam (2026-10-26 evening): no report share and an expiration more than 2 trading days after the report, or no confirmed date
    tail = "That covers every trading day until then, not just the report day."
    assert P.span_line(None, False, "2026-11-17", "2026-11-20") == tail                  # no confirmed date (NVDA today)
    assert P.span_line(None, True, "2026-10-27", "2026-11-20") == tail                   # confirmed, 18 trading days after (SHW-like, not separated)
    assert P.span_line(None, True, "2026-10-27", "2026-10-30") == tail                   # Tue report, Fri expiration: 3 trading days
    assert P.span_line(None, True, "2026-10-28", "2026-10-30") is None                   # Wed report, Fri expiration: 2 trading days
    assert P.span_line(None, True, "2026-11-25", "2026-11-30") is None                   # Thanksgiving: Fri 27 and Mon 30, 2 trading days
    assert P.span_line(0.058, True, "2026-10-27", "2026-11-20") is None                  # the report share says it instead
    assert P.span_line(None, False, None, "2026-11-20") == "That covers every trading day until then."     # no report before then
    assert P.span_line(None, False, "2026-12-15", "2026-11-20") == "That covers every trading day until then."
    vendor = {**NVDA, "report_pct": None, "report_date": None, "comparison": None, "typical_pct": 6.5, "span": tail}
    good = ("Options on NVIDIA price a move of ±8.9% ($19.65) by Nov 20, 2026. " + tail + " On its past report days, NVIDIA has moved 6.5% on "
            "the first day on average, over 21 reports. Options expect about the same swing as the stock has shown lately. "
            "Lately it has been calmer than usual compared with its past year.")
    assert P.read_problems(good, vendor) == []
    assert any("line S" in p for p in P.read_problems(good.replace(tail + " ", ""), vendor))
    assert any("line S" in p for p in P.read_problems(good.replace(" not just the report day", " not only the report"), vendor))
    assert "line S, word for word" in P.build_prompt(vendor)
