"""Ivy's Read in plain English (services/ivy_read_plain): the page's facts, the rules, the band check and the write loop."""
import asyncio
import json
import re

from app.services import ivy_read_plain as P

# NVDA as production showed it on 2026-10-22: Details ±8.9% / $19.65 by Nov 20, about 4.4% from the Nov 17 report, typical 6.5%
# over 21 reports ("less than usual"), spread +8.8 points (the row: about the same), RV rank 11.4 (quiet)
NVDA_VALUES = {"expected_move_pct": 0.0886, "expected_move_dollars": 19.65, "expiration_used": "2026-11-20", "chain_date": "2026-10-21",
               "iv_rv_spread_pp": 8.8, "rv_rank": 11.4, "rv_percentile": 4.4}
NVDA_REPORT = {"report_move_state": "ok", "report_move_pct": 0.044, "report_move": {"report_date": "2026-11-17"},
               "typical_move_pct": 6.5, "typical_n": 21, "move_comparison": "less than usual"}
NVDA = P.page_facts(symbol="NVDA", name="NVIDIA Corporation", fact_values=NVDA_VALUES, report=NVDA_REPORT)
OLD_NVDA = ("The market is pricing an implied move of ±8.9% (±$19.65) into the Nov 20, 2026 expiration, implying a range of $202.32 - "
            "$241.62 off a current price of $221.97. With 20-day realized vol sitting at just 25.1%, an RV rank of 11.4, and an IV-RV spread "
            "of +8.8pp, implied vol at 33.9% looks historically rich relative to what the stock has recently delivered, giving premium "
            "sellers a statistical edge on current conditions.")
GOOD = ("Options expect NVIDIA to move about ±8.9% ($19.65 either way) by Nov 20, 2026. About 4.4% of that comes from the Nov 17, 2026 "
        "report, less than the 6.5% the stock has moved on a typical report. Lately the stock has been calmer than usual for it.")


def test_the_facts_and_band_words_are_the_pages_own():
    assert NVDA["spread_word"] == "about the same" and NVDA["swing_band"] == "quiet" and NVDA["lately"] == "calmer than usual"
    lines = P.fact_lines(NVDA)
    assert lines["A"] == "Options price a move of ±8.9% ($19.65 either way) by Nov 20, 2026."
    assert lines["B"].startswith("About 4.4% of that comes from the report on Nov 17, 2026;")
    assert lines["C"] == "On a typical report the stock has moved 6.5% on the first day, over 21 reports; the report move is less than that."
    assert P.fact_lines({**NVDA, "spread_pp": 82.7, "spread_word": "pricey"})["E"] == \
        "Options expect 82.7 points more swing than the stock has shown lately, so they look pricey."
    assert P.spread_word(10.1) == "pricey" and P.spread_word(10.0) == "about the same" and P.spread_word(-10.1) == "cheap"
    # the band is the percentile's, like the page's row (MRNA, Oct 23: rank 19.6 but more than on 90% of days)
    mrna = P.page_facts(symbol="MRNA", name="Moderna", fact_values={**NVDA_VALUES, "rv_rank": 19.6, "rv_percentile": 90.9}, report=None)
    assert mrna["swing_band"] == "extreme" and mrna["lately"] == "much busier than usual"
    assert P.page_facts(symbol="X", name="X", fact_values={**NVDA_VALUES, "rv_rank": None}, report=None)["swing_band"] is None
    no_report = P.page_facts(symbol="X", name="X", fact_values=NVDA_VALUES, report={"report_move_state": "not_separated"})
    assert set(P.fact_lines(no_report)) == {"A", "D", "E"}
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
    assert any("leaves out the typical" in p for p in P.read_problems(GOOD.replace(", less than the 6.5% the stock has moved on a typical report", ""), NVDA))
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
    filler = ("Options on NVIDIA are pricing in a move of \u00b18.9% ($19.65 either way) by Nov 20, 2026. That percentage covers both upward "
              "and downward movement from the current price, so it describes a symmetric range rather than a directional forecast. "
              "Lately the stock has been calmer than usual for it.")
    no_report = {**NVDA, "report_pct": None, "typical_pct": None, "comparison": None}
    assert P.restatements(filler, no_report) == [2]
    assert any("sentence 2 restates" in p for p in P.read_problems(filler, no_report))
    assert P.restatements(GOOD, NVDA) == []
    assert P.lines_stated("About 4.4% of that comes from the Nov 17, 2026 report, less than the 6.5% the stock has moved on a typical report.", NVDA) == {"B", "C"}
    assert P.lines_stated("Options expect about the same swing the stock has shown lately.", NVDA) == {"E"}


def test_no_expected_move_means_no_read_and_no_model_call():
    cms = {**NVDA, "total_pct": None, "total_dollars": None}
    r = asyncio.run(P.write_read(cms, client=FakeClient([])))       # the fake has no drafts: any call would fail
    assert r["result"] == "no_move" and r["content"] is None and r["attempts"] == 0
