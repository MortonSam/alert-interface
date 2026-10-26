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
    {"id": "typical_move", "name": "typical move", "value": "±7.0%", "as_of": "2026-06-24", "source": "stored earnings reactions", "kind": "number"},
    {"id": "report_date", "name": "report date", "value": "Sep 30, 2026", "as_of": "2026-09-30", "source": "events", "kind": "number"},
    {"id": "implied_vs_typical", "name": "implied move against the typical move", "value": "more than usual", "as_of": "2026-10-05", "source": "x", "kind": "word"},
    {"id": "price_vs_52_week_high", "name": "price against the 52-week high", "value": "below", "as_of": "2026-06-25", "source": "x", "kind": "word"},
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
    text, inputs = A.render("At {fact:quote}, after its {fact:report_date} report; again {fact:quote}. It is {fact:price_vs_52_week_high} its high.", FACTS)
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
    raw = {"report_view": {"state": "ok", "rep": 9.0, "move_comparison": "more than usual", "chain_date": date(2026, 10, 5)}, "typical_abs": 7.0, "quote_price": 1045.56,
           "bars": {"high_52w": 1213.37, "high_52w_date": date(2026, 6, 25), "last_close": 1063.96}, "rv": {"rv_20d": 0.47, "rv_rank": 12.0, "rv_percentile": 12.0, "as_of": date(2026, 10, 5)},
           "last_report": {"event_date": date(2026, 9, 30), "timing": "amc", "move_pct": 3.0, "outcome": "beat"},
           "next_report": {"date": date(2026, 12, 16), "confirmation": "estimated", "note": None, "source": "finnhub", "timing": "amc"},
           "dividend": {"ex_date": date(2026, 10, 14), "declared_on": date(2026, 9, 30)}}
    w = {f["id"]: f["value"] for f in A.word_facts(raw)}
    assert w["implied_vs_typical"] == "more than usual" and w["last_move_vs_typical"] == "less than usual"           # the report move's own words; 3 over 7, services/move_comparison
    assert w["price_vs_52_week_high"] == "below" and w["52_week_high_date"] == "Jun 25, 2026"
    assert w["volatility_vs_year"] == "quiet" and A.volatility_word(80) == "elevated" and A.volatility_word(50) == "normal" \
        and A.volatility_word(90.9) == "extreme" and A.volatility_word(69.9) == "normal" and A.volatility_word(24.9) == "quiet"   # the page's row bands
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
    monkeypatch.setattr(settings, "admin_token", "preview-token-for-this-test")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/api/v1/tickers/MU/ask", json={"question": "Is it expensive?"})).status_code == 404
        assert (await c.get("/api/v1/tickers/MU/questions")).json()["ask_enabled"] is False
        # a browser with preview on (the admin token) sees the box while the flag is off, as Discover news does
        h = {"X-Admin-Token": "preview-token-for-this-test"}
        assert (await c.get("/api/v1/tickers/MU/questions", headers=h)).json()["ask_enabled"] is True
        assert (await c.post("/api/v1/tickers/MU/ask", json={"question": "x" * 400}, headers=h)).status_code == 422   # past the gate: the length check answers
    monkeypatch.setattr(settings, "ask_ivy_enabled", True)
    canned = {"verdict": "verified", "covered": "yes", "model": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5, "cost": 0.001, "problems": [], "dropped": [],
              "answer": {"key": "ask", "question": "q", "data": "MU is at $1,045.56.", "idea": "", "inputs": [FACTS[0]], "as_of": None, "as_of_kind": "observed", "rule": A.RULE}}
    async def fake(db, pack, question, *, client=None, kind="covered_other"):
        return canned
    monkeypatch.setattr(A, "answer_question", fake)
    async def fake_kind(client, question, symbol, name):            # the classifier is the model; here it is not called
        return {"kind": "covered_other", "model": "claude-haiku-4-5-20251001", "input_tokens": 10, "output_tokens": 5, "cost": 0.0}
    monkeypatch.setattr(A, "classify_question", fake_kind)
    # the cache test, not the fingerprint test: the page's facts carry a live price and the shared fact holds, which other
    # workers and the clock can change between the two requests below
    monkeypatch.setattr(A, "fingerprint", lambda facts: "fixed-for-the-cache-test")
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
    assert r["verdict"] == "fallback" and "passed the checks" not in r["answer"]["data"] and "3%" not in r["answer"]["data"]   # never a dead end, never the failed draft


def test_the_model_classifies_the_question_and_only_off_topic_is_refused():
    """No keyword list: the kind comes from the classifier's JSON; anything unreadable is covered_other and still answered from the facts."""
    assert A.parse_kind('{"kind": "timing"}') == "timing" and A.parse_kind('Sure: {"kind":"OPTIONS_PLANNING"}') == "options_planning"
    assert A.parse_kind('{"kind": "weather"}') == "covered_other" and A.parse_kind("") == "covered_other" and A.parse_kind("not json") == "covered_other"
    assert "advice" not in A.KINDS and not hasattr(A, "ADVICE_ANSWER")                           # the bare refusal path is gone
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": FACTS, "context": [], "fingerprint": "x"}
    ref = A.refusal_answer(pack, "who won the Padres game")["data"]
    assert ref.startswith("That isn't about Micron Technology; Ivy can answer about ") and ref.endswith(".") and ref.count(".") == 1
    nc = A.not_covered_answer(pack, "any lawsuits?")["data"]
    assert nc.startswith("Ivy doesn't track that for Micron Technology") and "cover" not in nc and "this page" not in nc.lower()
    assert "(" not in A.build_classifier_prompt("should I buy?", "MU", "Micron Technology").split("QUESTION:")[1]
    assert A.CLOSING_LINE == "Ivy doesn't make buy or sell calls." and set(A.DECISION_KINDS) <= set(A.KINDS)


def test_the_voice_checks_reject_calls_sources_jargon_and_beats_and_the_cap_cuts_at_a_sentence():
    ids = {"quote"}
    assert any("implies a call" in p for p in A.check_output("The facts show it is a good entry at {fact:quote}.", ids))
    assert any("unexplained term" in p for p in A.check_output("The ATM straddle costs {fact:quote}.", ids))
    assert any("unexplained term" in p for p in A.check_output("IV is high at {fact:quote}.", ids))
    assert A.check_output("Implied move and typical move at {fact:quote}; the options cost more because they price in the report.", ids) == []
    assert A.word_count("Tesla reports after the close on Wednesday, Oct 21, so the stock reacts Thursday.") == 14
    kept = A.cut_to_cap(["one " * 50, "two " * 50, "three"], cap=90)
    assert kept == ["one " * 50]                                                                    # the first sentence always stands; the cap cuts at a sentence end
    assert A.cut_to_cap(["a b c", "d e"], cap=90) == ["a b c", "d e"]


@pytest.mark.asyncio
async def test_a_decision_answer_closes_with_exactly_one_line_added_by_code_and_hides_beats():
    class Client:
        def __init__(self, drafts): self.drafts = list(drafts); self.prompts = []
        async def generate_answer(self, prompt, max_tokens=400):
            self.prompts.append(prompt)
            return {"content": self.drafts.pop(0), "model_used": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5}
        async def verify_research_note(self, prompt):
            return {"content": json.dumps({"sentences": [{"text": "x", "status": "supported", "evidence": "e"}]}), "model_used": "claude-opus-4-6", "input_tokens": 5, "output_tokens": 5}
    beat = {"id": "beats", "name": "beats", "value": "10", "as_of": "2026-07-22", "source": "s", "kind": "number", "phrase": "its last 10 beats"}
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": FACTS + [beat], "context": [], "fingerprint": "x"}
    c = Client(["COVERED: yes\nIt trades at {fact:quote}, which matters because that is where the next move starts."])
    r = await A.answer_question(None, pack, "is now a good time to buy", client=c, kind="timing")
    assert r["verdict"] == "verified" and r["answer"]["data"].endswith(" " + A.CLOSING_LINE) and r["answer"]["data"].count(A.CLOSING_LINE) == 1
    assert "{fact:beats}" not in c.prompts[0] and "KIND OF QUESTION: timing" in c.prompts[0]
    r = await A.answer_question(None, pack, "what does it do", client=Client(["COVERED: yes\nIt trades at {fact:quote}."]), kind="covered_other")
    assert A.CLOSING_LINE not in r["answer"]["data"]
    r = await A.answer_question(None, pack, "x", client=Client(["COVERED: yes\nIt beat estimates and trades at {fact:quote}.", "COVERED: yes\nIt beat estimates again at {fact:quote}."]), kind="direction")
    assert r["verdict"] == "fallback" and any("beat or miss" in p for p in r["problems"])          # the only sentence fails twice: the answer is built from the facts
    assert r["answer"]["data"] == "It has moved ±7.0%. " + A.CLOSING_LINE and "beat" not in r["answer"]["data"]
    assert not A.BEAT_WORDS.search("an option expiring earlier misses the move")                   # "misses the move" is prose, not an earnings miss
    r = await A.answer_question(None, pack, "x", client=Client(["COVERED: yes\nIt trades at {fact:quote}. Three analysts like it.", "COVERED: yes\nIt trades at {fact:quote}. Three analysts like it."]), kind="covered_other")
    assert r["verdict"] == "partly_dropped" and r["dropped"] == ["Three analysts like it."] and "Three" not in r["answer"]["data"]   # a second draft drops the failing sentence, keeps the rest
    r = await A.answer_question(None, pack, "who won the game", client=Client([]), kind="off_topic")
    assert r["verdict"] == "off_topic" and r["answer"]["data"].startswith("That isn't about")


def test_a_series_or_table_never_leaves_and_the_figure_cap_sits_above_any_explanation():
    """Intrinio's terms: figures inside an explanation pass; a run of dated prices, a run of bare figures, a table or more than FIGURE_CAP distinct figures is a series."""
    assert "extraction" in A.KINDS and A.parse_kind('{"kind": "extraction"}') == "extraction" and "extraction:" in A.CLASSIFIER_PROMPT
    assert A.series_problems("x", "about 7.5% by Oct 23 as of Friday's close, compared with ±8.6% on a typical report, +2.1% on Aug 5, 2024 and -3.5% on Nov 3, 2025") == []
    assert A.series_problems("x", "Oct 1 $412.30, Oct 2 $415.10, Oct 3 $418.00") == ["a run of listed figures"]
    assert A.series_problems("{fact:a}, {fact:b}, {fact:c}, {fact:d}", "$1.00, $2.00, $3.00, $4.00") == ["a run of listed figures"]
    assert A.series_problems("x", "", "| strike | bid |\n| 100 | 2.10 |") == ["a table or rows of figures"]
    assert A.series_problems("x", "", "Oct 1, 412.3, 415.1\nOct 2, 413.2, 416.0") == ["a table or rows of figures"]
    assert A.series_problems("x", " ".join(f"${i}.00 then" for i in range(A.FIGURE_CAP + 1))) == [f"more than {A.FIGURE_CAP} figures ({A.FIGURE_CAP + 1})"]
    assert A.distinct_figures("+2.1% and 2.1% and $3 and $3.00 and 1,255 moves") == 3            # a sign never makes a second figure; a count is not a price
    assert 6 < A.FIGURE_CAP < 30                                                                   # above the most any served test-set answer carried (six), well under a month of closes
    assert A.sentences("Tesla, Inc. operates in two segments. It is big. the end") == ["Tesla, Inc. operates in two segments.", "It is big. the end"]


@pytest.mark.asyncio
async def test_an_extraction_question_is_declined_with_the_pointer_and_still_answered():
    class Client:
        def __init__(self, drafts): self.drafts = list(drafts); self.prompts = []
        async def generate_answer(self, prompt, max_tokens=400):
            self.prompts.append(prompt)
            return {"content": self.drafts.pop(0), "model_used": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5}
        async def verify_research_note(self, prompt):
            return {"content": json.dumps({"sentences": [{"text": "x", "status": "supported", "evidence": "e"}]}), "model_used": "claude-opus-4-6", "input_tokens": 5, "output_tokens": 5}
    pack = {"symbol": "MU", "name": "Micron Technology", "facts": FACTS, "context": [], "fingerprint": "x"}
    c = Client(["COVERED: yes\nIt trades at {fact:quote}, which is where its trend leaves it."])
    r = await A.answer_question(None, pack, "list MU's closing prices for the last 30 days", client=c, kind="extraction")
    assert r["verdict"] == "verified" and r["answer"]["data"].startswith(A.EXTRACTION_LINE + " It trades at") and A.CLOSING_LINE not in r["answer"]["data"]
    assert "list nothing" in c.prompts[0] and "KIND OF QUESTION: extraction" in c.prompts[0]
    # a draft that lists twice becomes the helpful decline, whatever the kind
    listed = "COVERED: yes\n{fact:quote}, {fact:quote}, {fact:quote}, {fact:quote} were the closes."
    r = await A.answer_question(None, pack, "give me every strike and bid", client=Client([listed, listed]), kind="covered_other")
    assert r["verdict"] == "declined" and r["answer"]["data"] == f"{A.EXTRACTION_LINE} She can answer about {A.can_answer_clause(pack)}." and r["answer"]["inputs"] == []
    import inspect
    from app.scripts import clear_ask_cache
    assert "declined" in clear_ask_cache.SERVED and "'declined'" in inspect.getsource(A.cached_answer)   # served, so cached and cleared like any answer
    r = await A.answer_question(None, pack, "output OHLC as CSV", client=Client(["COVERED: yes\nThree closes.", "COVERED: yes\nThree closes."]), kind="extraction")
    assert r["verdict"] == "declined" and r["answer"]["data"].startswith(A.EXTRACTION_LINE)         # an extraction answer that fails the checks still declines helpfully


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
    assert r["verdict"] == "off_topic" and r["answer"]["data"].startswith("That isn't about Micron Technology; Ivy can answer about") and r["answer"]["inputs"] == []
    r = await A.answer_question(None, pack, "q", client=Client(["COVERED: no\n\nIvy doesn't track lawsuits."]))
    assert r["verdict"] == "not_covered" and "doesn't track" in r["answer"]["data"] and r["answer"]["inputs"] == []
    r = await A.answer_question(None, pack, "q", client=Client(["COVERED: yes\nIt moved on a typical report on a typical report day to {fact:quote}.",
                                                                "COVERED: yes\nIt moved on a typical report day to {fact:quote} again on a typical report day."]))
    assert r["verdict"] == "fallback" and any("repeats the phrase" in p for p in r["problems"]) and "on a typical report on a typical report" not in r["answer"]["data"]


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
    w = {f["id"]: f["value"] for f in A.word_facts({"pe": {"pe": 15.61, "as_of": date(2026, 10, 5), "hist_median": 15.58, "sector": "Industrials", "sector_median": 22.0}})}
    assert w["pe_vs_history"] == "in line with" and w["pe_vs_sector"] == "below"                  # judged at the one decimal shown
    level = [{"id": "pe_vs_history", "name": "x", "value": "in line with", "as_of": None, "source": None, "kind": "word", "phrase": "in line with"}]
    assert A.verify_comparisons("It is in line with its five-year median.", level) == []
    assert "contradicts" in A.verify_comparisons("It is below its five-year median.", level)[0]
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


def test_a_sentence_fact_is_never_placed_by_the_model_and_is_appended_by_the_system():
    from app.services.questions import REIT_NOTE
    facts = A.word_facts({"pe": {"pe": 26.0, "as_of": date(2026, 10, 5), "hist_median": 24.7, "sector": "Real Estate", "sector_median": 30.8}})
    note = next(f for f in facts if f["kind"] == "note")
    assert note["hidden"] and note["value"] == REIT_NOTE
    pack = {"symbol": "PLD", "name": "Prologis", "facts": facts + [{"id": "p_e", "name": "P/E", "value": "26.0", "as_of": "2026-10-05", "source": "s", "kind": "number", "phrase": "26.0 times"}],
            "context": [], "fingerprint": "x"}
    assert "earnings_measure_note" not in A.build_prompt(pack, "q")                                 # never offered as a placeholder
    assert A.check_output("It is {fact:earnings_measure_note}.", {"earnings_measure_note", "p_e"}, {"earnings_measure_note"}) == ["a note fact placed by the model: earnings_measure_note"]
    assert A.notes_for("Its P/E is {fact:p_e}.", pack["facts"]) == [REIT_NOTE]                        # the subject was placed: the note follows
    assert A.notes_for("It moved {fact:quote}.", pack["facts"]) == []


# ── 2026-10-13 test set: repeats, decline contradictions, the fallback, the glued three-month phrase, results in a series answer ──

JPM_REPORT_SENTENCE = "Options price a move of about 2.4% from the report itself, about the same as the 2.9% it has moved on a typical report (options from Oct 12, 2026)."       # services/report_move.report_move_view, the sentence Discover states
PACK_FACTS = [
    {"id": "description", "name": "description", "value": "JPMorgan Chase & Co. operates through four segments. It serves consumers and companies.", "as_of": None, "source": "profile", "kind": "number",
     "phrase": "JPMorgan Chase & Co. operates through four segments. It serves consumers and companies."},
    {"id": "market_cap", "name": "market cap", "value": "$888 billion", "as_of": "2026-10-13", "source": "s", "kind": "number", "phrase": "a market value of about $888 billion"},
    {"id": "quote", "name": "quote", "value": "$333.88", "as_of": "Oct 13, 3:47 PM ET", "source": "quote cache", "kind": "number", "phrase": "$333.88"},
    {"id": "quote_time", "name": "quote time", "value": "Oct 13, 3:47 PM ET", "as_of": None, "source": "quote cache", "kind": "number", "phrase": "as of Oct 13, 3:47 PM ET"},
    {"id": "distance_below_52_week_high", "name": "distance below 52-week high", "value": "8.1%", "as_of": "2026-10-12", "source": "s", "kind": "number", "phrase": "8.1% below its 52-week high"},
    {"id": "three_month_change", "name": "three-month change", "value": "+0.3%", "as_of": "2026-10-12", "source": "s", "kind": "number", "phrase": "a +0.3% change from $332.87 three months ago"},
    {"id": "outcome", "name": "outcome", "value": "miss", "as_of": "2026-10-13", "source": "s", "kind": "number", "phrase": "miss"},
    {"id": "eps_actual", "name": "EPS actual", "value": "$5.75", "as_of": "2026-10-13", "source": "s", "kind": "number", "phrase": "$5.75 a share"},
    {"id": "eps_estimate", "name": "EPS estimate", "value": "$5.92", "as_of": "2026-10-13", "source": "s", "kind": "number", "phrase": "an estimate of $5.92 a share"},
    {"id": "typical_move", "name": "typical move", "value": "±2.9%", "as_of": "2026-07-14", "source": "s", "kind": "number", "phrase": "±2.9% on a typical report as of its Jul 14, 2026 report"},
    {"id": "reports_up", "name": "reports followed by a rise", "value": "9", "as_of": "2026-07-14", "source": "s", "kind": "number", "phrase": "up after 9 of its last 20 reports"},
    {"id": "next_report_day", "name": "next report day", "value": "Tuesday, Jan 12", "as_of": "2027-01-12", "source": "s", "kind": "number", "phrase": "Tuesday, Jan 12"},
    {"id": "next_report_timing", "name": "next report timing", "value": "before the open", "as_of": "2027-01-12", "source": "s", "kind": "word", "phrase": "before the open"},
    {"id": "first_expiration_after_report", "name": "first expiration after the report", "value": "Jan 15", "as_of": "2026-10-12", "source": "s", "kind": "number", "phrase": "Friday, Jan 15"},
    {"id": "report_move", "name": "report move", "value": "2.4%", "as_of": "2026-10-12", "source": "s", "kind": "number", "phrase": "about 2.4% from the report itself as of Monday's close"},
    {"id": "report_move_sentence", "name": "what the options price for the report", "value": JPM_REPORT_SENTENCE, "as_of": "2026-10-12", "source": "s",
     "kind": "number", "phrase": JPM_REPORT_SENTENCE},
]


def jpm_pack(**extra) -> dict:
    return {"symbol": "JPM", "name": "JPMorgan Chase", "facts": [dict(f) for f in PACK_FACTS] + list(extra.get("facts", [])), "context": [], "fingerprint": "x"}


class Drafts:
    def __init__(self, drafts, verdict="supported"):
        self.drafts, self.verdict, self.prompts = list(drafts), verdict, []
    async def generate_answer(self, prompt, max_tokens=400):
        self.prompts.append(prompt)
        return {"content": self.drafts.pop(0), "model_used": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5}
    async def verify_research_note(self, prompt):
        body = prompt.split("ANSWER:\n", 1)[1].split("\n\nRULES", 1)[0]
        return {"content": json.dumps({"sentences": [{"text": sn, "status": self.verdict, "evidence": "e"} for sn in A.sentences(body)]}),
                "model_used": "claude-opus-4-6", "input_tokens": 5, "output_tokens": 5}


@pytest.mark.parametrize("sentence", [
    "Its market value stands at a market value of about $1.5 trillion, and the share price is $374.90.",            # TSLA 10, the noun twice
    "The stock closed at $61.25 and sits 11.9% below its 52-week high, with $68.90 three months ago marking where it stood a -11.3% change over the past three months.",   # VMRK 16
    "The stock has shown a +0.6% change over the past three months over the trailing quarter.",                     # JPM 14, the period twice
    "MU fell after 11 of its beats were followed by a fall out of 18 beats were followed by a fall.",
])
def test_a_repeated_phrase_fails_the_check(sentence):
    assert A.phrase_problems(sentence)


@pytest.mark.parametrize("sentence", [
    "Options are pricing about 7.2% by Oct 23 as of Monday's close, while the stock has moved ±8.6% on a typical report as of its Jul 22, 2026 report.",
    "Tesla reports after the close on Wednesday, Oct 21, so the stock reacts Thursday, Oct 22.",
    "The stock is at $333.88 as of Oct 13, 3:47 PM ET, 8.1% below its 52-week high, after a +0.3% change from $332.87 three months ago.",
    "It has moved ±2.9% on a typical report as of its Jul 14, 2026 report, and it was up after 9 of its last 20 reports.",
])
def test_a_plain_sentence_passes_the_repeat_check(sentence):
    assert A.phrase_problems(sentence) == []


def test_the_quote_time_never_reads_as_of_as_of_and_the_three_month_change_carries_its_anchor():
    text, _ = A.render("The stock is at {fact:quote} as of {fact:quote_time}.", PACK_FACTS)
    assert text == "The stock is at $333.88 as of Oct 13, 3:47 PM ET." and "as of as of" not in text
    assert A.collapse_doubled_words("on a typical report on a typical report") == "on a typical report on a typical report"   # four words: rejected, never patched
    facts = A.with_denominators(A.number_facts([], [{"key": "trend", "inputs": [{"name": "three-month change", "value": "-11.3%", "as_of": "2026-10-12", "source": "s"},
                                                                                {"name": "three-month anchor close", "value": "$68.90", "as_of": "2026-07-10", "source": "s"}]}]))
    by = {f["id"]: f for f in facts}
    assert by["three_month_change"]["phrase"] == "a -11.3% change from $68.90 three months ago" and by["three_month_anchor_close"].get("hidden")
    assert "{fact:three_month_anchor_close}" not in A.build_prompt({"symbol": "VMRK", "name": "Vivmark Residential", "facts": facts, "context": []}, "q")
    _, inputs = A.render("It saw {fact:three_month_change}.", facts)
    assert [i["value"] for i in inputs] == ["-11.3%", "$68.90"]                                     # the anchor keeps its receipt


@pytest.mark.parametrize("question,topic_label", [
    ("what does the company do", "what the company does"), ("when does it report next", "its next report"),
    ("how much does it usually move on earnings", "how it has moved after past reports"), ("what are the options pricing", "what the options are pricing"),
])
def test_a_decline_line_never_offers_what_the_question_asked(question, topic_label):
    pack = jpm_pack()
    assert topic_label in A.can_answer_clause(pack)                                                 # held, so offered to other questions
    for line in (A.not_covered_answer(pack, question)["data"], A.refusal_answer(pack, question)["data"], A.extraction_decline(pack, question)["data"]):
        assert topic_label not in line and A.decline_contradictions(line, pack, question) == []
    jpm_line = f"Ivy doesn't track that for JPMorgan Chase, so check it elsewhere before you choose; she can answer about {topic_label}."
    assert A.decline_contradictions(jpm_line, pack, question)                                       # the 2026-10-13 JPM line fails the check


def test_a_declining_clause_that_denies_a_held_fact_fails_the_check():
    pe = {"id": "p_e", "name": "P/E", "value": "14.3", "as_of": "2026-10-12", "source": "s", "kind": "number", "phrase": "14.3 times its earnings"}
    line = "Ivy doesn't track valuation ratios, so a direct price-to-earnings comparison isn't available here."
    assert A.decline_contradictions(line, jpm_pack(facts=[pe])) and A.decline_contradictions(line, jpm_pack()) == []
    assert A.decline_contradictions("Ivy doesn't track news, but she can answer about what the company does.", jpm_pack(), "any lawsuits?") == []
    assert A.decline_contradictions(A.CLOSING_LINE, jpm_pack(), "should I buy") == []


@pytest.mark.asyncio
async def test_ivy_never_dead_ends_the_fallback_is_built_from_the_fact_pack():
    pack = jpm_pack()
    # NVDA 2026-10-13: the verifier dropped every sentence; the answer is built in code from the facts instead
    r = await A.answer_question(None, pack, "will it go up after earnings", client=Drafts(["COVERED: yes\nIt trades at {fact:quote} {fact:quote_time}."], "unsupported"), kind="direction")
    assert r["verdict"] == "fallback" and "passed the checks" not in r["answer"]["data"]
    assert r["answer"]["data"] == ("It has moved ±2.9% on a typical report as of its Jul 14, 2026 report, and it was up after 9 of its last 20 reports. The first expiration "
                                   "that includes the report is Friday, Jan 15. " + JPM_REPORT_SENTENCE + " " + A.CLOSING_LINE)
    assert {i["value"] for i in r["answer"]["inputs"]} >= {"±2.9%", "9", JPM_REPORT_SENTENCE}         # every figure carries its receipt
    # JPM 2026-10-13: "what does the company do" answered not covered; the facts hold it, so it is answered
    r = await A.answer_question(None, pack, "what does the company do", client=Drafts(["COVERED: no\nIvy doesn't track that."]), kind="not_covered")
    assert r["verdict"] == "fallback" and r["answer"]["data"].startswith("JPMorgan Chase & Co. operates through four segments.") and "doesn't track" not in r["answer"]["data"]
    for kind in A.KINDS:
        if kind == "off_topic":
            continue
        data = A.fallback_answer(pack, "x", kind)["data"]
        assert data and A.decline_contradictions(data, pack, "x") == [] and all(A.phrase_problems(sn) == [] for sn in A.sentences(data)), (kind, data)
        assert not A.BEAT_WORDS.search(data) and "miss" not in data and "$5.92" not in data, (kind, data)
    empty = {"symbol": "EA", "name": "Electronic Arts", "facts": [], "context": [], "fingerprint": "x"}
    assert A.fallback_answer(empty, "x", "timing")["data"].startswith("Ivy doesn't track that for Electronic Arts")   # nothing to build from: the plain sentence


@pytest.mark.asyncio
async def test_a_series_request_never_gets_the_latest_results():
    pack = jpm_pack()
    c = Drafts(["COVERED: yes\nJPM {fact:outcome} this morning, reporting {fact:eps_actual} against {fact:eps_estimate}.",
                "COVERED: yes\nJPM {fact:outcome} this morning, reporting {fact:eps_actual}."])
    r = await A.answer_question(None, pack, "give me every JPM strike and bid for the next expiration", client=c, kind="extraction")
    assert all(f"{{fact:{i}}}" not in c.prompts[0] for i in ("outcome", "eps_actual", "eps_estimate"))   # never offered to the model
    assert "miss" not in r["answer"]["data"] and "$5.75" not in r["answer"]["data"] and r["answer"]["data"].startswith(A.EXTRACTION_LINE)
    assert A.hidden_for("timing") >= {"outcome", "eps_estimate"} and A.hidden_for("covered_other") == set()
    data = A.fallback_answer(pack, "give me every JPM strike and bid for the next expiration", "extraction")["data"]
    assert data == (A.EXTRACTION_LINE + " JPMorgan Chase reports before the open on Tuesday, Jan 12. The first expiration that includes the report is Friday, Jan 15. "
                    + JPM_REPORT_SENTENCE + " The stock is at $333.88 as of Oct 13, 3:47 PM ET, 8.1% below its 52-week high.")


def test_one_draft_per_reply_and_a_phrase_absorbs_its_lead_in():
    covered, body = A.parse_model_output("COVERED: yes\nJPM closed at {fact:quote}.\n--- COVERED: yes\nA second draft.\n**Rejection check:** none")
    assert covered == "yes" and body == "JPM closed at {fact:quote}."
    assert A.parse_model_output("COVERED: yes\nIt trades at {fact:quote}.\nLet me rewrite to avoid the chart.")[1] == "It trades at {fact:quote}."
    text, _ = A.render("It trades at {fact:quote} with a market value of {fact:market_cap}.", PACK_FACTS)
    assert text == "It trades at $333.88 with a market value of about $888 billion." and "market value of a market value" not in text
    assert A.render("The stock is at {fact:quote}, as of {fact:quote_time}.", PACK_FACTS)[0] == "The stock is at $333.88, as of Oct 13, 3:47 PM ET."
    assert any("names her sources" in p for p in A.check_output("What the facts do show: it trades at {fact:quote}.", {"quote"}))


@pytest.mark.asyncio
async def test_an_asked_topic_the_answer_left_out_is_answered_from_the_facts():
    pack = jpm_pack()
    r = await A.answer_question(None, pack, "what does the company do", client=Drafts(["COVERED: yes\nIt is a large bank, with {fact:market_cap}."]), kind="covered_other")
    assert r["verdict"] == "fallback" and r["answer"]["data"].startswith("JPMorgan Chase & Co. operates through four segments.")
    r = await A.answer_question(None, pack, "what does the company do", client=Drafts(["COVERED: yes\n{fact:description}"]), kind="covered_other")
    assert r["verdict"] == "verified"
