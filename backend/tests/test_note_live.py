"""No fast-changing number is frozen into a research note (Sam, 2026-11-02): services/note_live and its use in the writer, the
checker and the served note."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest

from app.services import note_live as L

VALUES = {
    "price": {"name": "last close", "value": "$215.38", "as_of": "2026-10-30", "source": "price_bars_shadow", "kind": "number"},
    "pe": {"name": "P/E", "value": "27.2", "as_of": "2026-10-30", "source": "pe_snapshots", "kind": "number"},
    "pe_vs_history": {"name": "P/E against its five-year median", "value": "below", "as_of": "2026-10-30", "source": None, "kind": "word"},
    "volatility_20d": {"name": "20-day realized volatility", "value": "8.1%", "as_of": "2026-10-30", "source": None, "kind": "number"},
}


@pytest.mark.parametrize("sentence", [
    "NVIDIA's shares closed at $215.38, up 4.3% over three months.",
    "The stock trades at 27 times trailing earnings.",
    "Its market capitalization is $5.2 trillion.",
    "Options imply a 6.6% move for the report.",
    "The dividend yield is 3.1%.",
    "Shares sit 10% below the 52-week high.",
    "Realized volatility of 30.6% is above its usual level.",
    "The P/E of 27.2 is below its five-year median of 52.0.",
])
def test_a_typed_fast_changing_figure_is_named(sentence):
    assert L.typed_fast_figure(sentence)
    assert L.sentence_problems(sentence)


@pytest.mark.parametrize("sentence", [
    # durable figures from filings, and the served notes' own wording on 2026-11-02 (all 497 audited: none typed a live figure)
    "Revenue for the quarter ended July 26, 2026 reached $96.22 billion, up 105.9% from $46.74 billion in the same quarter a year earlier.",
    "The company completed a $500 million accelerated share repurchase, retiring 9.7 million shares at an average price of $51.54.",
    "The quarterly dividend was also raised from $0.60 to $0.67 per share.",
    "Q4 2026 delivery guidance of 22,000 to 23,000 homes at an average sales price of $370,000 to $380,000.",
    "Gross margin over the trailing twelve months was 74.7% against a five-year average of 68.5%.",
    "Key items include the pending 2026 Drop Down and commodity price volatility heading into the back half of the year.",
    "U.S. combined market capitalization of approximately $47.1 trillion across its listed companies.",
    "Revenue across multiple segments rose 8% from a year earlier.",
    # slots, and a comparison as a word slot
    "The stock closed at {live:price}.",
    "The P/E of {live:pe} sits {live:pe_vs_history} its five-year median.",
])
def test_durable_figures_and_slots_pass(sentence):
    assert L.sentence_problems(sentence) == []


def test_a_slot_compared_in_its_own_words_or_an_invented_slot_is_named():
    assert any("own words" in w for w in L.sentence_problems("The P/E of {live:pe} is below its history."))
    assert any("does not exist" in w for w in L.sentence_problems("The yield is {live:dividend_yield}."))


def test_the_writer_gets_slot_names_and_never_a_value():
    block = L.prompt_block({"price", "pe", "pe_vs_history"})
    assert "{live:price}" in block and "{live:pe_vs_history}" in block and "{live:market_value}" not in block
    assert "$" not in block.replace("{live:", "") and "27.2" not in block
    assert "none on file" in L.prompt_block(set())


def test_a_note_is_filled_at_read_and_a_sentence_without_its_figure_is_left_out():
    note = {"bottom_line": "The stock closed at {live:price}. Its implied move is {live:implied_move}. Margins held.",
            "what_they_do": "Chips.",
            "highlights": [{"lead": "Valuation", "detail": "The P/E of {live:pe} sits {live:pe_vs_history} its five-year median."},
                           {"lead": "Options at {live:implied_move}", "detail": "Text."}],
            "watch": [], "risks": []}
    out = L.fill_structured(note, VALUES)
    assert out["bottom_line"] == "The stock closed at $215.38. Margins held."
    assert out["highlights"] == [{"lead": "Valuation", "detail": "The P/E of 27.2 sits below its five-year median."}]
    assert [i["name"] for i in L.used_inputs(note, None, VALUES)] == ["last close", "P/E", "P/E against its five-year median"]
    assert L.fill_markdown("- **Lead:** Closed at {live:price}. Implied {live:implied_move}.\n## Head", VALUES) == "- **Lead:** Closed at $215.38.\n## Head"
    assert L.fill_sentence("Volatility runs at a {live:volatility_20d} pace.", VALUES) == "Volatility runs at an 8.1% pace."


def test_keep_available_drops_a_slot_with_no_figure_as_the_note_is_written():
    note = {"bottom_line": "Closed at {live:price}. Moves {live:implied_move}.", "what_they_do": "", "highlights": [], "watch": [], "risks": []}
    assert L.keep_available(note, VALUES)["bottom_line"] == "Closed at {live:price}."


def test_the_checkers_claims_get_their_slots_back():
    slotted = "# X\n\nThe stock closed at {live:price}. Margins held."
    ver = {"claims": [{"claim": "closed at $215.38", "sentence": "The stock closed at $215.38.", "verdict": "supported", "reason": "r"},
                      {"claim": "Margins held", "sentence": "Margins held.", "verdict": "supported", "reason": "r"}]}
    out = L.reslot(ver, slotted, VALUES)
    assert out["claims"][0] == {"claim": "closed at {live:price}", "sentence": "The stock closed at {live:price}.", "verdict": "supported", "reason": "r"}
    assert out["claims"][1]["sentence"] == "Margins held."
    later = dict(VALUES, price={**VALUES["price"], "value": "$220.00"})
    assert L.fill_verification(out, later)["claims"][0]["claim"] == "closed at $220.00"      # served with today's value


def test_the_rules_drop_a_typed_figure_and_name_it_on_the_retry():
    from app.services.note_rules import enforce, note_problems
    draft = {"bottom_line": "NVIDIA trades at 27 times earnings. Watch margins against the five-year average.", "what_they_do": "Chips.",
             "highlights": [{"lead": "Price", "detail": "Shares closed at $215.38. Margin 75.0% against a five-year average of 65.2%."}],
             "watch": [], "risks": []}
    problems = note_problems(draft)
    assert any("fast-changing figure" in p and "27 times" in p for p in problems)
    assert any("fast-changing figure" in p and "$215.38" in p for p in problems)
    out = enforce(draft)
    assert out["bottom_line"] == "Watch margins against the five-year average."
    assert out["highlights"][0]["detail"] == "Margin 75.0% against a five-year average of 65.2%."


def test_the_prompts_carry_no_market_value_and_the_checker_gets_the_live_figures():
    from app.services import research_note_service as R
    t = SimpleNamespace(symbol="ZZLV", name="Z", sector="Tech", industry="Chips", market_cap=5_190_658_058_146)
    gen = R._build_generation_prompt(t, None, None, [], None, L.prompt_block({"price"}))
    assert "MARKET CAP" not in gen and "5.19" not in gen and "{live:price}" in gen and "Never type a figure that changes" in gen
    ver = R._build_verification_prompt("The stock closed at $215.38.", None, None, [], t, L.live_evidence({"price": VALUES["price"]}))
    assert "MARKET CAP" not in ver and "last close: $215.38 (as of 2026-10-30)" in ver


def test_no_price_based_multiple_or_market_value_is_stored_or_served():
    from app.services import research_note_service as R
    f = {"forward_pe": 14.5, "pe_ttm": 25.6, "ps_ttm": 16.3, "peg_ttm": 0.46, "forward_peg": 0.26, "gross_margin_ttm": 74.7, "roe_ttm": 110.1}
    assert R.durable_financials(f) == {"gross_margin_ttm": 74.7, "roe_ttm": 110.1}
    assert R._build_stats_object(SimpleNamespace(symbol="ZZLV", market_cap=5e12), [])["market_cap"] is None


def test_a_visitor_is_served_the_note_filled_with_receipts_and_no_stored_multiple():
    from app.routers.research_notes import _note_for_reader
    now = datetime.now(timezone.utc)
    sc = {"bottom_line": "The stock closed at {live:price}.", "what_they_do": "Chips.", "highlights": [], "watch": [], "risks": [],
          "stats": {"latest_quarter_date": "2026-08-26"}, "financials": {"pe_ttm": 25.6, "forward_peg": 0.26, "gross_margin_ttm": 74.7}}
    claims = [{"claim": "closed at {live:price}", "sentence": "The stock closed at {live:price}.", "verdict": "supported", "reason": "r"},
              {"claim": "Chips", "sentence": "Chips.", "verdict": "supported", "reason": "r"}]
    note = SimpleNamespace(id=uuid.uuid4(), ticker_id=uuid.uuid4(), generated_at=now, source_filings=[], content="# X\n\nThe stock closed at {live:price}.",
                           model_used="m", input_tokens=1, output_tokens=1, structured_content=sc,
                           verification={"claims": claims, "summary": {}, "version": 2}, verified_at=now, verification_model="m",
                           status="complete", error=None, created_at=now, updated_at=now)
    read = _note_for_reader(note, admin=False, hidden=False, values=VALUES)
    assert read.structured_content["bottom_line"] == "The stock closed at $215.38."
    assert read.structured_content["financials"] == {"gross_margin_ttm": 74.7}
    assert "{live:" not in read.content and "$215.38" in read.content
    assert read.live_inputs == [{"name": "last close", "value": "$215.38", "as_of": "2026-10-30", "source": "price_bars_shadow"}]
    assert "{live:" not in json.dumps(read.verification.model_dump() if hasattr(read.verification, "model_dump") else read.verification)
    empty = _note_for_reader(note, admin=False, hidden=False, values={})
    assert empty.structured_content["bottom_line"] == "" and empty.live_inputs == []      # no figure on file: the sentence is left out


@pytest.mark.asyncio
async def test_the_retry_reads_the_prompt_from_the_cache_and_the_cost_counts_cached_tokens(monkeypatch):
    from app.services import anthropic_client as AC
    from app.services.research_cost import estimate_cost_usd
    sent = []

    async def create(self, method, **kw):
        sent.append(kw["messages"][0]["content"])
        usage = SimpleNamespace(input_tokens=40, output_tokens=10, cache_creation_input_tokens=0 if len(sent) > 1 else 7000,
                                cache_read_input_tokens=7000 if len(sent) > 1 else 0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")], usage=usage)
    monkeypatch.setattr(AC.AnthropicClient, "_create", create)
    monkeypatch.setattr(AC.AnthropicClient, "__init__", lambda self, **kw: None)
    c = AC.AnthropicClient()
    first = await c.generate_research_note("PROMPT")
    again = await c.generate_research_note("PROMPT", "\n\nRETRY")
    assert sent[0] == [{"type": "text", "text": "PROMPT", "cache_control": {"type": "ephemeral"}}]
    assert sent[1] == [{"type": "text", "text": "PROMPT", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "\n\nRETRY"}]
    assert first["cache_write_tokens"] == 7000 and again["cache_read_tokens"] == 7000
    # $3 a million uncached, 1.25x to write, 0.1x to read, $15 a million out (claude-sonnet-4-6)
    assert estimate_cost_usd("claude-sonnet-4-6", 40, 10, 7000, 0) == round((40 * 3 + 10 * 15 + 7000 * 3 * 1.25) / 1e6, 4)
    assert estimate_cost_usd("claude-sonnet-4-6", 40, 10, 0, 7000) == round((40 * 3 + 10 * 15 + 7000 * 3 * 0.1) / 1e6, 4)
