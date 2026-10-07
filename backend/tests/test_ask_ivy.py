"""Ask Ivy: the no-typed-numbers rule with adversarial fixtures, the comparison check against word facts, substitution with
receipts, the verifier's sentence verdicts, normalization and the cache key, word facts from the strip's numbers, and the
route behind its flag."""
import json
import re
from datetime import date

import pytest

from app.services import ask_ivy as A

FACTS = [
    {"id": "quote", "name": "quote", "value": "$1,045.56", "as_of": "Oct 6, 4:00 PM ET", "source": "quote cache", "kind": "number"},
    {"id": "typical_move", "name": "typical move", "value": "±7.0%", "as_of": "2026-06-24", "source": "historical_reactions", "kind": "number"},
    {"id": "report_date", "name": "report date", "value": "Sep 30, 2026", "as_of": "2026-09-30", "source": "events", "kind": "number"},
    {"id": "implied_vs_typical", "name": "implied move against the typical move", "value": "more than usual", "as_of": "2026-10-05", "source": "x", "kind": "word"},
    {"id": "price_vs_52w_high", "name": "price against the 52-week high", "value": "below", "as_of": "2026-06-25", "source": "x", "kind": "word"},
    {"id": "volatility_vs_year", "name": "volatility against its year", "value": "quiet", "as_of": "2026-10-05", "source": "x", "kind": "word"},
    {"id": "dividend_status", "name": "next dividend", "value": "estimated", "as_of": "2026-10-14", "source": "x", "kind": "word"},
]
IDS = {f["id"] for f in FACTS}


@pytest.mark.parametrize("text", [
    "The stock is at $1,045.56 right now.",                       # a typed price
    "It moved 3% after the report.",                               # a typed percent
    "It has beaten estimates 18 times.",                           # a digit
    "It rose twice as much as usual.",                             # twice
    "That is double the typical move.",                            # double
    "Roughly half of its beats were followed by a fall.",          # half as a fraction
    "About a quarter of the reports moved it more.",               # quarter as a fraction
    "A dozen reports moved it more.",                              # dozen
    "Five of the last reports moved it more.",                     # a number word
    "Over the last twenty reports it moved {fact:typical_move}.",  # twenty
    "It trades near {fact:quote} and {fact:not_a_fact}.",          # an unknown placeholder
    "One sentence. Two sentences. Three sentences. Four sentences.",  # four sentences
    "You should buy it before the dividend.",                      # a recommendation
    "It costs {fact:quote} today.",                                # fine... but a brace below
    "It costs {fact:quote today.",                                 # a malformed placeholder
])
def test_output_check_rejects_typed_numbers_number_words_unknown_ids_length_and_recommendations(text):
    problems = A.check_output(text, IDS)
    if text == "It costs {fact:quote} today.":
        assert problems == []
    else:
        assert problems, text


def test_output_check_passes_prose_with_placeholders_and_window_names():
    text = ("Micron is at {fact:quote}, below its 52-week high, and its 20-day realized volatility is quiet. "
            "On a typical report it moves {fact:typical_move}. The next session's move is the 1-day move.")
    assert A.check_output(text, IDS) == []
    assert A.check_output("Its results for the third quarter and the first half of the year are in the S&P 500 record.", IDS) == []   # periods, not fractions


def test_comparisons_are_checked_against_word_facts():
    assert A.verify_comparisons("Options price more than usual for this report.", FACTS) == []
    assert A.verify_comparisons("It trades below its 52-week high and volatility is quiet.", FACTS) == []
    assert "contradicts" in A.verify_comparisons("Options price less than usual.", FACTS)[0]
    assert "contradicts" in A.verify_comparisons("Realized volatility is elevated.", FACTS)[0]
    assert "no stored comparison" in A.verify_comparisons("The report is confirmed for after the close.", FACTS)[0]
    assert A.verify_comparisons("The dividend is estimated, not yet declared.", FACTS) == []                        # "not yet declared" asserts estimated
    assert "contradicts" in A.verify_comparisons("The dividend was declared.", FACTS)[0]


def test_render_substitutes_values_and_collects_receipts_once():
    text, inputs = A.render("At {fact:quote}, after its {fact:report_date} report; again {fact:quote}. It is {fact:price_vs_52w_high} its high.", FACTS)
    assert text == "At $1,045.56, after its Sep 30, 2026 report; again $1,045.56. It is below its high."
    assert [i["name"] for i in inputs] == ["quote", "report date"]                                                   # word facts carry no receipt; a value once
    assert inputs[0]["as_of"] == "Oct 6, 4:00 PM ET" and inputs[1]["source"] == "events"


def test_model_output_parsing_and_verdicts():
    assert A.parse_model_output("COVERED: no\n\nThe facts do not cover that. Here is {fact:quote}.") == ("no", "The facts do not cover that. Here is {fact:quote}.")
    assert A.parse_model_output("Just an answer.")[0] == "partly"
    assert A.parse_model_output("COVERED: maybe\nx")[0] == "partly"
    kept, dropped = A.apply_verdicts(["A.", "B.", "C."], [{"status": "supported"}, {"status": "unsupported"}, {"status": "supported"}])
    assert kept == ["A.", "C."] and dropped == ["B."]
    assert A.apply_verdicts(["A.", "B."], [{"status": "supported"}]) == ([], ["A.", "B."])                          # misaligned verdicts keep nothing
    assert A.parse_verdicts('```json\n{"sentences": [{"text": "A.", "status": "supported", "evidence": "e"}]}\n```')[0]["status"] == "supported"


def test_normalization_folds_ticker_name_stopwords_and_synonyms():
    a = A.normalize_question("Why did Micron drop after earnings?", "MU", "Micron Technology")
    b = A.normalize_question("why did MU fall after the report", "MU", "Micron Technology")
    assert a == b == "after earnings fall"
    assert A.normalize_question("Is Micron expensive right now?", "MU", "Micron Technology") == A.normalize_question("Is MU pricey?", "MU", "Micron Technology")
    k1 = A.cache_key("MU", a, "fp1"); k2 = A.cache_key("MU", a, "fp2")
    assert k1 != k2 and len(k1) == 32                                                                                 # a changed fact pack is a new key


def test_word_facts_come_from_the_strips_numbers_with_the_shared_thresholds():
    raw = {"implied": {"implied_pct": 0.09, "chain_date": date(2026, 10, 5)}, "typical_abs": 7.0, "quote_price": 1045.56,
           "bars": {"high_52w": 1213.37, "high_52w_date": date(2026, 6, 25), "last_close": 1063.96}, "rv": {"rv_20d": 0.47, "rv_rank": 12.0, "as_of": date(2026, 10, 5)},
           "last_report": {"event_date": date(2026, 9, 30), "timing": "amc", "move_pct": 3.0, "outcome": "beat"},
           "next_report": {"date": date(2026, 12, 16), "confirmation": "estimated", "note": None, "source": "finnhub", "timing": "amc"},
           "dividend": {"ex_date": date(2026, 10, 14), "declared_on": date(2026, 9, 30)}}
    w = {f["id"]: f["value"] for f in A.word_facts(raw)}
    assert w["implied_vs_typical"] == "more than usual" and w["last_move_vs_typical"] == "less than usual"           # 9 over 7 and 3 over 7, services/move_comparison
    assert w["price_vs_52w_high"] == "below" and w["52_week_high_date"] == "Jun 25, 2026"
    assert w["volatility_vs_year"] == "quiet" and A.volatility_word(80) == "elevated" and A.volatility_word(50) == "normal"
    assert w["last_report_outcome"] == "beat" and w["last_report_direction"] == "rose" and w["last_report_timing"] == "after the close"
    assert w["next_report_status"] == "estimated" and w["next_report_timing"] == "after the close" and w["dividend_status"] == "declared"
    assert A.word_facts({}) == []


def test_number_facts_keep_one_fact_per_name_and_value():
    sents = [{"key": "stock", "inputs": [{"name": "quote", "value": "$1", "as_of": "d", "source": "s"}]}]
    qs = [{"key": "reaction_normal", "inputs": [{"name": "quote", "value": "$1", "as_of": "d", "source": "s"}, {"name": "report date", "value": "Sep 30, 2026", "as_of": "2026-09-30", "source": "events"}]},
          {"key": "implied_big", "inputs": [{"name": "report date", "value": "Dec 16, 2026", "as_of": "2026-12-16", "source": "events"}]}]
    ids = [f["id"] for f in A.number_facts(sents, qs)]
    assert ids == ["quote", "report_date", "report_date_implied_big"]
    assert A.fingerprint(A.number_facts(sents, qs)) != A.fingerprint(A.number_facts(sents, qs[:1]))


def test_prompt_shows_values_and_forbids_typing_them():
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": FACTS, "context": ["MU is at $1,045.56."], "fingerprint": "x"}
    p = A.build_prompt(pack, "Is it expensive?")
    assert "{fact:quote} = quote: $1,045.56" in p and "[word]" in p and "Never type a number" in p and "Never give a recommendation" in p


@pytest.mark.asyncio
async def test_the_route_is_absent_behind_the_flag_and_serves_a_checked_answer_when_on(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "ask_ivy_enabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/api/v1/tickers/MU/ask", json={"question": "Is it expensive?"})).status_code == 404
        assert (await c.get("/api/v1/tickers/MU/questions")).json()["ask_enabled"] is False
    monkeypatch.setattr(settings, "ask_ivy_enabled", True)
    canned = {"verdict": "verified", "covered": "yes", "model": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5, "cost": 0.001, "problems": [], "dropped": [],
              "answer": {"key": "ask", "question": "q", "data": "MU is at $1,045.56.", "idea": "", "inputs": [FACTS[0]], "as_of": None, "as_of_kind": "observed", "rule": A.RULE}}
    async def fake(db, pack, question, *, client=None):
        return canned
    monkeypatch.setattr(A, "answer_question", fake)
    from app.services import draft_limiter
    async def no_limit(*a, **k):
        return None
    monkeypatch.setattr(draft_limiter, "check_limit", no_limit)        # the limiter has its own tests; this one runs many times a day locally
    monkeypatch.setattr(draft_limiter, "record_use", no_limit)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/tickers/MU/questions")).json()["ask_enabled"] is True
        r = await c.post("/api/v1/tickers/MU/ask", json={"question": "Is it expensive right now, really, " + "x" * 300})
        assert r.status_code == 422
        import uuid
        token = uuid.uuid4().hex                                                                   # a new question each run: the log persists between runs
        r = await c.post("/api/v1/tickers/MU/ask", json={"question": f"Is it expensive right now {token}?"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answer"]["data"] == "MU is at $1,045.56." and body["cached"] is False
        r2 = await c.post("/api/v1/tickers/MU/ask", json={"question": f"is MU pricey {token}"})   # the same normalized question: served from the log
        assert r2.status_code == 200 and r2.json()["cached"] is True


def test_phrases_read_in_a_sentence_and_receipts_keep_the_quantity():
    facts = A.number_facts([{"key": "stock", "inputs": [{"name": "distance below 52-week high", "value": "13.8%", "as_of": "2026-06-25", "source": "s"},
                                                           {"name": "1-day move window", "value": "close Sep 30, 2026 to close Oct 1, 2026", "as_of": "2026-10-01", "source": "trading calendar"}]}], [])
    by = {f["id"]: f for f in facts}
    assert by["distance_below_52_week_high"]["phrase"] == "13.8% below its 52-week high"
    assert by["move_session"]["value"] == "Oct 1, 2026" and by["move_session"]["phrase"] == "over the next session, Oct 1, 2026"
    text, inputs = A.render("It sits {fact:distance_below_52_week_high} and rose {fact:move_session}.", facts)
    assert text == "It sits 13.8% below its 52-week high and rose over the next session, Oct 1, 2026."
    assert [(i["name"], i["value"]) for i in inputs] == [("distance below 52-week high", "13.8%"), ("session the move was measured over", "Oct 1, 2026")]
    text, _ = A.render("A rise — then a fall.", facts)
    assert "—" not in text


@pytest.mark.asyncio
async def test_a_rejected_draft_is_rewritten_once_and_a_second_failure_is_never_shown():
    class Client:
        def __init__(self, drafts):
            self.drafts = list(drafts); self.calls = 0
        async def generate_answer(self, prompt, max_tokens=400):
            self.calls += 1
            return {"content": self.drafts.pop(0), "model_used": "claude-sonnet-4-6", "input_tokens": 100, "output_tokens": 20}
        async def verify_research_note(self, prompt):
            return {"content": json.dumps({"sentences": [{"text": "x", "status": "supported", "evidence": "e"}]}), "model_used": "claude-opus-4-6", "input_tokens": 50, "output_tokens": 10}
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": FACTS, "context": [], "fingerprint": "x"}
    c = Client(["COVERED: yes\nIt moved one time to {fact:quote}.", "COVERED: yes\nIt moved to {fact:quote}."])
    r = await A.answer_question(None, pack, "q", client=c)
    assert c.calls == 2 and r["retried"] and r["verdict"] == "verified" and r["answer"]["data"] == "It moved to $1,045.56."
    c = Client(["COVERED: yes\nIt moved twice.", "COVERED: yes\nIt moved 3% again."])
    r = await A.answer_question(None, pack, "q", client=c)
    assert r["verdict"] == "rejected" and r["answer"]["inputs"] == [] and "passed the checks" in r["answer"]["data"]


@pytest.mark.parametrize("q", [
    "Should I buy Micron before the dividend?", "should i sell MU now", "Is it a good time to buy?", "Is now a good time to get in?",
    "Is Micron worth buying?", "Is it worth it?", "Would you buy this stock?", "Is MU a buy?", "Buy or sell?", "Is this a good investment?",
    "What should I do with my shares?", "Do you recommend Micron?", "Should I hold or take profits?", "Is it the right time to sell?",
])
def test_advice_questions_are_classified_without_a_model(q):
    assert A.classify_question(q, "MU", "Micron Technology") == "advice"


@pytest.mark.parametrize("q", ["Will Micron go up after earnings?", "Where will the stock be next year?", "Is it more volatile than usual?",
                               "How did it react to the last report?", "What happens on the ex-dividend date?", "Is Micron expensive right now?", "Why did it fall?"])
def test_predictions_and_data_questions_go_to_the_model(q):
    assert A.classify_question(q, "MU", "Micron Technology") == "normal"


@pytest.mark.parametrize("q", ["hello", "What's the weather in Boise?", "Tell me a joke", "Who are you?", "What is the capital of France?", "best pizza recipe"])
def test_off_topic_questions_get_the_fixed_sentence(q):
    assert A.classify_question(q, "MU", "Micron Technology") == "off_topic"
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": [], "context": [], "fingerprint": "x"}
    assert A.fixed_answer("off_topic", pack, q)["data"] == "Ivy only answers questions about Micron Technology's stock."
    assert A.fixed_answer("advice", pack, q)["data"] == "Ivy cannot give investment advice."


def test_fact_phrases_are_noun_phrases_and_repeated_phrases_are_rejected():
    verbs = re.compile(r"\b(?:was|were|is|are|has|have|had|moved|followed|rose|fell|gained|lost|beat|missed)\b")
    for name, phrase in A.PHRASES.items():
        assert not verbs.search(phrase), (name, phrase)
    assert A.phrase_for("beats followed by a fall", "11") == "11 of its beats"
    assert "followed by" in (A.repeated_phrase("MU fell after 11 of its beats were followed by a fall out of 18 beats were followed by a fall.") or "")
    assert A.repeated_phrase("It moves ±7.0% on a report; on a report it moves less.") is None                   # three words repeat, not four
    assert A.absorb_literals("Reported Sep 30, 2026 at $1,045.56, a beat.", FACTS) == "Reported {fact:report_date} at {fact:quote}, a beat."
    assert A.absorb_literals("At {fact:quote} already.", FACTS) == "At {fact:quote} already."
    assert A.repeated_phrase("The stock rose +3.0% over the next session, Oct 1, 2026.") is None


@pytest.mark.asyncio
async def test_a_covered_no_draft_shows_only_the_fixed_sentence_and_a_repeat_is_rejected():
    class Client:
        def __init__(self, drafts): self.drafts = list(drafts)
        async def generate_answer(self, prompt, max_tokens=400):
            return {"content": self.drafts.pop(0), "model_used": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5}
        async def verify_research_note(self, prompt):
            return {"content": json.dumps({"sentences": [{"text": "x", "status": "supported", "evidence": "e"}]}), "model_used": "claude-opus-4-6", "input_tokens": 5, "output_tokens": 5}
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": FACTS, "context": [], "fingerprint": "x"}
    r = await A.answer_question(None, pack, "q", client=Client(["COVERED: off\n\nI can tell you about the weather instead: {fact:quote}."]))
    assert r["verdict"] == "off_topic" and r["answer"]["data"] == "Ivy only answers questions about Micron Technology's stock." and r["answer"]["inputs"] == []
    r = await A.answer_question(None, pack, "q", client=Client(["COVERED: no\n\nThis page's data does not cover valuation."]))
    assert r["verdict"] == "not_covered" and "doesn't cover" in r["answer"]["data"] and r["answer"]["inputs"] == []
    r = await A.answer_question(None, pack, "q", client=Client(["COVERED: yes\nIt moved on a typical report on a typical report day to {fact:quote}.",
                                                                "COVERED: yes\nIt moved on a typical report day to {fact:quote} again on a typical report day."]))
    assert r["verdict"] == "rejected" and any("repeats the phrase" in p for p in r["problems"])


def test_counts_carry_their_denominator_and_signed_moves_read_as_a_move():
    facts = A.with_denominators(A.number_facts([], [
        {"key": "beat_fell", "inputs": [{"name": "beats", "value": "18", "as_of": "2026-06-24", "source": "s"}, {"name": "beats followed by a fall", "value": "11", "as_of": "2026-06-24", "source": "s"}]},
        {"key": "reaction_normal", "inputs": [{"name": "reports moving more", "value": "15", "as_of": "2026-06-24", "source": "s"}, {"name": "reports in the sample", "value": "20", "as_of": "2026-06-24", "source": "s"},
                                               {"name": "1-day move", "value": "+3.0%", "as_of": "2026-10-01", "source": "s"}]}]))
    by = {f["id"]: f for f in facts}
    assert by["beats_followed_by_a_fall"]["phrase"] == "11 of its last 18 beats" and by["beats_followed_by_a_fall"]["companions"] == ["beats"]
    assert by["reports_moving_more"]["phrase"] == "15 of its last 20 reports"
    assert by["1_day_move"]["phrase"] == "a +3.0% move"
    text, inputs = A.render("It fell after {fact:beats_followed_by_a_fall}; the stock had {fact:1_day_move}.", facts)
    assert text == "It fell after 11 of its last 18 beats; the stock had a +3.0% move."
    assert A.collapse_doubled_words("reported after after the close; the the stock") == "reported after the close; the stock"
    assert A.collapse_doubled_words("it had had enough") == "it had enough" and A.collapse_doubled_words("on a typical report on a typical report") == "on a typical report on a typical report"
    assert [(i["name"], i["value"]) for i in inputs] == [("beats followed by a fall", "11"), ("beats", "18"), ("1-day move", "+3.0%")]   # the denominator's receipt too


def test_pe_word_facts_and_the_valuation_verdict_check():
    w = {f["id"]: f["value"] for f in A.word_facts({"pe": {"pe": 14.34, "as_of": date(2026, 10, 5), "hist_median": 16.8, "sector": "Information Technology", "sector_median": 43.4}})}
    assert w["pe_vs_history"] == "below" and w["pe_vs_sector"] == "below"
    assert A.check_output("Its P/E is {fact:p_e}, which looks cheap.", {"p_e"}) == ["valuation verdict: cheap"]
    assert A.check_output("Its P/E is {fact:p_e}, below its five-year median.", {"p_e"}) == []
    facts = [{"id": "pe_vs_sector", "name": "x", "value": "below", "as_of": None, "source": None, "kind": "word", "phrase": "below"}]
    assert "contradicts" in A.verify_comparisons("It sits above its sector median.", facts)[0]


def test_real_estate_note_fact_and_the_session_share_reads_as_one_clause():
    w = {f["id"]: f["value"] for f in A.word_facts({"pe": {"pe": 26.0, "as_of": date(2026, 10, 5), "hist_median": 24.7, "sector": "Real Estate", "sector_median": 30.8}})}
    assert w["earnings_measure_note"].startswith("Real estate companies are usually judged against funds from operations")
    assert "earnings_measure_note" not in {f["id"] for f in A.word_facts({"pe": {"pe": 14.3, "as_of": date(2026, 10, 5), "hist_median": 16.8, "sector": "Information Technology", "sector_median": None}})}
    facts = A.with_denominators(A.number_facts([], [{"key": "pe_compare", "inputs": [{"name": "sessions below today's P/E", "value": "38%", "as_of": "2026-10-05", "source": "s"},
                                                                                     {"name": "sessions compared", "value": "871", "as_of": "2026-10-05", "source": "s"}]}]))
    text, inputs = A.render("It has been lower in {fact:sessions_below_today_s_p_e}.", facts)
    assert text == "It has been lower in 38% of its 871 sessions over the past five years."
    assert [i["value"] for i in inputs] == ["38%", "871"]
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": facts, "context": [], "fingerprint": "x"}
    assert "{fact:sessions_compared}" not in A.build_prompt(pack, "q") and "{fact:sessions_below_today_s_p_e}" in A.build_prompt(pack, "q")   # the denominator is not offered on its own
