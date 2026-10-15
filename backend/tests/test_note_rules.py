"""Research notes (services/note_rules, research_note_service): at most three points a section with no minimum, a comparison
behind every figure, nothing the ticker page already shows, a neutral Bottom Line, no dashes, correct articles; the verdict
counts come from the claims, never the model's summary, and a self-correcting reason is re-verified."""
import json
from datetime import date

import pytest

from app.services import note_rules as NR
from app.services.eps_year_ago import eps_line, quarter_for_report, year_ago_pairs
from app.services.note_comparisons import comparison_lines


def test_articles_before_numbers():
    assert NR.clean_text("a 18-of-20 record and a 8% rise, a 11.5% margin, an 5% drop, a 80-store plan") == \
        "an 18-of-20 record and an 8% rise, an 11.5% margin, a 5% drop, an 80-store plan"
    assert NR.clean_text("A 18,000-unit backlog, a 1.8% yield, a 180-day window, an 8 million") == \
        "An 18,000-unit backlog, a 1.8% yield, a 180-day window, an 8 million"


def test_no_dashes():
    assert NR.clean_text("Margins rose — driven by mix — in 2025–2026, up 5–7%.") == "Margins rose, driven by mix, in 2025 to 2026, up 5 to 7%."
    assert "—" not in NR.clean_text("a—b") and "–" not in NR.clean_text("a – b")


def _p(lead, detail):
    return {"lead": lead, "detail": detail}


def test_point_rules():
    assert NR.point_problems(_p("Margin", "Gross margin was 75.0% against a five-year average of 65.2%.")) == []
    assert NR.point_problems(_p("Revenue", "Revenue grew 62% to $57 billion, up from $35.1 billion a year earlier.")) == []
    assert "states a figure with no comparison" in NR.point_problems(_p("Revenue", "Revenue reached $57 billion."))[0]
    assert NR.point_problems(_p("Guidance", "Management expects demand to stay firm into next year.")) == []      # no figure, no comparison needed
    for repeat in ("It beat estimates in 18 of 20 quarters.", "The stock fell 6% after its last report, against a typical 4%.",
                   "Its beat rate is 90%, above peers.", "The post-earnings move averaged 5%, above the sector."):
        assert any("repeats" in w for w in NR.point_problems(_p("x", repeat))), repeat
    assert any("verdict" in w for w in NR.point_problems(_p("Valuation", "Shares look undervalued against peers.")))


def test_at_most_three_points_no_minimum_and_a_neutral_bottom_line():
    draft = {"rating": "bullish", "what_they_do": "Makes chips — mostly GPUs.",
             "bottom_line": "Watch data center revenue against the year-ago quarter. The setup is compelling. Watch export rules.",
             "highlights": [_p(f"P{i}", f"Revenue up {i}% from a year earlier.") for i in range(5)],
             "watch": [], "risks": [_p("Bare", "Inventory was $10 billion."), _p("Ok", "Inventory rose 20% from a year earlier.")]}
    probs = NR.note_problems(draft)
    assert "highlights: 5 points, at most 3" in probs and "bottom_line: gives a verdict on the stock" in probs
    note = NR.enforce(draft)
    assert len(note["highlights"]) == 3 and note["watch"] == [] and [p["lead"] for p in note["risks"]] == ["Ok"]
    assert note["bottom_line"] == "Watch data center revenue against the year-ago quarter. Watch export rules."
    assert note["what_they_do"] == "Makes chips, mostly GPUs." and "rating" not in note
    assert NR.note_problems(note) == []


def test_eps_against_a_year_earlier_from_sec_quarters():
    qs = [(date(2025, 7, 27), 1.05), (date(2025, 10, 26), 1.30), (date(2026, 1, 25), 1.76), (date(2026, 4, 26), 2.39), (date(2026, 7, 26), 2.22),
          (date(2024, 10, 27), 0.78)]
    pairs = year_ago_pairs(qs)
    assert pairs[0]["period_end"] == date(2026, 7, 26) and pairs[0]["year_ago_eps"] == 1.05 and pairs[0]["pct"] == 111.4
    assert eps_line(pairs[0]) == "EPS $2.22, up 111.4% from $1.05 a year ago"
    assert eps_line(next(p for p in pairs if p["period_end"] == date(2026, 4, 26))) == "EPS $2.39. No EPS figure from the same quarter a year earlier is on file."
    assert quarter_for_report(pairs, date(2026, 8, 26))["period_end"] == date(2026, 7, 26)
    assert quarter_for_report(pairs, date(2027, 1, 1)) is None
    loss = year_ago_pairs([(date(2025, 6, 30), -0.40), (date(2026, 6, 30), 0.25)])[0]
    assert loss["pct"] is None and eps_line(loss) == "EPS $0.25 against -$0.40 a year ago, swung to a profit"
    lines = comparison_lines(pairs, (18.0, 40), "Information Technology", [], {"gross_margin_ttm": 75.0, "gross_margin_5y": 65.2})
    assert lines[0].startswith("Diluted EPS (SEC filings), quarter ended Jul 26, 2026: $2.22 against $1.05")
    assert any("median EPS change against the same quarter a year earlier +18.0%" in x for x in lines)
    assert any(x.startswith("Gross margin (financial data provider): 75.0%") for x in lines)


class FakeClient:
    """The model's drafts in order; records each prompt."""
    def __init__(self, *drafts):
        self.drafts, self.prompts = list(drafts), []
    async def generate_research_note(self, prompt):
        self.prompts.append(prompt)
        return {"content": json.dumps(self.drafts.pop(0)), "model_used": "claude-sonnet-4-6", "input_tokens": 100, "output_tokens": 50}


@pytest.mark.asyncio
async def test_a_draft_that_breaks_the_rules_is_written_once_more_then_enforced(monkeypatch):
    from app.services import research_note_service as R
    bad = {"bottom_line": "A compelling setup.", "what_they_do": "x", "highlights": [_p("Beats", "Beat estimates in 18 of 20 quarters.")], "watch": [], "risks": []}
    good = {"bottom_line": "Watch margins against the five-year average.", "what_they_do": "x",
            "highlights": [_p("Margin", "Gross margin 75.0% against a five-year average of 65.2%.")], "watch": [], "risks": []}
    fake = FakeClient(bad, good)
    monkeypatch.setattr(R, "AnthropicClient", lambda **kw: fake)
    note, used = await R._generate_structured("PROMPT", "ZZNR")
    assert len(fake.prompts) == 2 and "YOUR PREVIOUS DRAFT BROKE THESE RULES" in fake.prompts[1] and "repeats what the ticker page shows" in fake.prompts[1]
    assert note["highlights"][0]["lead"] == "Margin" and used["attempts"] == 2 and used["input_tokens"] == 200
    # a second bad draft is enforced in code: the repeat dropped, the verdict sentence dropped
    fake = FakeClient(bad, bad)
    monkeypatch.setattr(R, "AnthropicClient", lambda **kw: fake)
    note, _ = await R._generate_structured("PROMPT", "ZZNR")
    assert note["highlights"] == [] and note["bottom_line"] == ""


class FakeVerifier:
    def __init__(self, *answers):
        self.answers = list(answers)
    async def verify_research_note(self, prompt):
        return {"content": json.dumps(self.answers.pop(0)), "model_used": "claude-opus-4-6", "input_tokens": 10, "output_tokens": 5}


@pytest.mark.asyncio
async def test_counts_come_from_the_claims_and_a_self_correcting_reason_is_verified_again(monkeypatch):
    from types import SimpleNamespace
    from app.services import research_note_service as R
    first = {"summary": {"supported": 9, "unsupported": 0, "contradicted": 0},          # the model's own summary: never used
             "claims": [{"claim": "A", "verdict": "supported", "reason": "The filing says so."},
                        {"claim": "B", "verdict": "supported", "reason": "Supported, actually unsupported on reflection."},
                        {"claim": "C", "verdict": "contradicted", "reason": "The filing says otherwise."}]}
    again = {"claims": [{"claim": "B", "verdict": "unsupported", "reason": "The sources do not state it."}]}
    monkeypatch.setattr(R, "AnthropicClient", lambda **kw: FakeVerifier(first, again))
    t = SimpleNamespace(symbol="ZZNR", name="Z", sector=None, industry=None, market_cap=None)
    v, _, _, _ = await R._run_verification("note", None, None, [], t)
    assert v["summary"] == {"supported": 1, "unsupported": 1, "contradicted": 1}
    assert v["claims"][1]["verdict"] == "unsupported" and v["claims"][1]["reason"] == "The sources do not state it."


def test_recount_note_verdicts_settles_each_claim_and_counts_the_summary():
    from app.scripts.recount_note_verdicts import recount
    from app.services.verification_verdicts import UNSETTLED_REASON, problems
    stored = {"summary": {"supported": 3, "unsupported": 0, "contradicted": 0}, "model": "x",
              "claims": [{"claim": "A", "status": "supported", "evidence": "The filing says so."},
                         {"claim": "B", "status": "supported", "evidence": "Re-evaluating: actually this is unsupported."},
                         {"claim": "C", "status": "partly", "evidence": "Close enough."}]}
    assert problems(stored)
    new, changes = recount(stored)
    assert problems(new) == [] and new["model"] == "x"
    assert new["summary"] == {"supported": 1, "unsupported": 2, "contradicted": 0}
    b = new["claims"][1]
    assert (b["claim"], b["verdict"], b["status"], b["reason"], b["evidence"]) == ("B", "unsupported", "unsupported", UNSETTLED_REASON, UNSETTLED_REASON)
    assert b["prior_reason"] == "Re-evaluating: actually this is unsupported."
    assert new["claims"][0] == {**stored["claims"][0], "verdict": "supported", "reason": "The filing says so."}
    assert len(changes) == 3 and changes[-1].startswith("summary ")
    assert recount(new)[1] == []                                    # a corrected note needs nothing more
