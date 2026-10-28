"""Sam, 2026-10-28: a served research note states only what its check confirmed, the check reads Item 1 of the 10-K, a note that
loses more than MAX_LOST sentences is written again once and then held; and the note EPS check skips figures labeled adjusted,
non-GAAP, trailing, four quarters or year-to-date (production's EMR, ES, CBOE, EL and CRL notes)."""
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services import note_claims as NC
from app.services.note_valuation import eps_disagreement, named_quarter, quarter_text_eps
from app.services.verification_verdicts import parse_claims

pytestmark = pytest.mark.xdist_group(name="note_confirmed_only")

# BNY's note on production, 2026-10-27 (15 supported, 2 unsupported, both in What they do)
BNY_DOES = ("BNY, The Bank of New York Mellon Corporation, is a global custody bank and asset servicer whose revenue is driven by fees for "
            "securities servicing, clearing, asset and wealth management, and treasury services. The firm holds assets on behalf of "
            "institutional clients and earns net interest income on the resulting deposit balances, making its revenues sensitive to "
            "both market activity levels and interest rates.")
BNY_POINT = ("Diluted EPS over the last four quarters was $9.04, up 30.4% from the $6.93 recorded over the four quarters before. Each of "
             "the four most recent quarters has shown year-over-year EPS growth ranging from 24.5% to 41.8%.")


def _bny():
    sc = {"what_they_do": BNY_DOES, "bottom_line": "BNY has sustained a multi-quarter run of double-digit EPS growth.",
          "highlights": [{"lead": "Sustained EPS acceleration", "detail": BNY_POINT}], "watch": [], "risks": [], "stats": {}}
    claims = [
        {"claim": "BNY, The Bank of New York Mellon Corporation, is a global custody bank and asset servicer", "verdict": "supported", "reason": "metadata"},
        {"claim": "whose revenue is driven by fees for securities servicing, clearing, asset and wealth management, and treasury services",
         "verdict": "unsupported", "reason": "no source"},
        {"claim": "The firm holds assets on behalf of institutional clients and earns net interest income on the resulting deposit balances, "
                  "making its revenues sensitive to both market activity levels and interest rates", "verdict": "unsupported", "reason": "no source"},
        {"claim": "Diluted EPS over the last four quarters was $9.04, up 30.4% from the $6.93 recorded over the four quarters before",
         "verdict": "supported", "reason": "source 4"},
        {"claim": "Most recent quarter: 2026-10-15", "verdict": "unsupported", "reason": "a date line"},
    ]
    return sc, {"claims": claims}


def test_the_served_note_drops_each_sentence_holding_an_unconfirmed_claim():
    sc, ver = _bny()
    s, v, c = NC.served(sc, ver, BNY_DOES + "\n- **Sustained EPS acceleration:** " + BNY_POINT)
    assert s["what_they_do"] == ""                                        # both sentences held a claim the check could not confirm
    assert s["highlights"][0]["detail"] == BNY_POINT                     # confirmed: shown whole
    # the claims a visitor sees: the supported ones whose sentence is still shown (the first sat in a dropped sentence)
    assert [x["claim"][:28] for x in v["claims"]] == ["Diluted EPS over the last fo"]
    assert "net interest income" not in c and "$9.04" in c
    r = NC.review(sc, ver)
    assert len(r["lost"]) == 2 and r["unlocated"] == []                  # the date line is the strip's, neither dropped nor counted
    assert NC.lost(sc, ver) == 2


def test_a_point_goes_whole_when_its_lead_or_all_its_text_is_unconfirmed():
    sc = {"what_they_do": "", "bottom_line": "", "watch": [], "risks": [],
          "highlights": [{"lead": "Record backlog", "detail": "Backlog reached $5 billion. Orders rose."},
                         {"lead": "Margins", "detail": "Gross margin was 40%. It rose from 38%."},
                         {"lead": "Cash", "detail": "Cash was $2 billion."}]}
    ver = {"claims": [{"claim": "Record backlog", "sentence": "Record backlog", "verdict": "unsupported", "reason": ""},
                      {"claim": "It rose from 38%", "verdict": "contradicted", "reason": ""},
                      {"claim": "Cash was $2 billion", "verdict": "unsupported", "reason": ""}]}
    s, _v, _c = NC.served(sc, ver, None)
    assert s["highlights"] == [{"lead": "Margins", "detail": "Gross margin was 40%."}]
    assert sorted(NC.review(sc, ver)["lost"]) == sorted(["Backlog reached $5 billion.", "Orders rose.", "It rose from 38%.", "Cash was $2 billion."])


def test_the_verifiers_copied_sentence_is_found_before_the_claims_words():
    us = NC.units({"what_they_do": "Alpha sells widgets. Beta sells widgets too."})
    assert NC.locate({"claim": "sells widgets", "sentence": "Beta sells widgets too."}, us) == 1
    assert NC.locate({"claim": "Gamma makes engines for ships"}, us) is None


def test_parse_claims_keeps_the_sentence_in_either_reading():
    clean = '{"claims": [{"claim": "Revenue rose", "sentence": "Revenue rose 5%.", "verdict": "supported", "reason": "MD&A"}]}'
    assert parse_claims(clean)[0]["sentence"] == "Revenue rose 5%."
    loose = '{"claims": [{"claim": "It sells "Tide" soap", "sentence": "It sells "Tide" soap.", "verdict": "unsupported", "reason": "none"}]}'
    row = parse_claims(loose)[0]
    assert row["claim"] == 'It sells "Tide" soap' and row["sentence"] == 'It sells "Tide" soap.' and row["verdict"] == "unsupported"


def test_check_outcome_holds_a_note_that_loses_more_than_max_lost_or_an_unconfirmed_claim_it_cannot_place():
    from app.services.research_note_service import check_outcome
    sc = {"what_they_do": "A one. B two. C three. D four. E five.", "bottom_line": "", "highlights": [], "watch": [], "risks": []}
    bad = lambda n: {"claims": [{"claim": t, "verdict": "unsupported", "reason": ""} for t in ["A one", "B two", "C three", "D four"][:n]]}
    assert check_outcome(sc, bad(NC.MAX_LOST)) is None
    assert "more than 3" in check_outcome(sc, bad(NC.MAX_LOST + 1))
    assert "no sentence" in check_outcome(sc, {"claims": [{"claim": "Zebra quantum harbor", "verdict": "contradicted", "reason": ""}]})


# ── the regenerate-once rule, through the background path ────────────────────

SYM = "ZZNC"


async def _cleanup(s):
    await s.execute(text("DELETE FROM research_notes WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
    await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
    await s.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def ticker_id():
    from app.database import ScriptSessionLocal
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        tid = (await s.execute(text("""INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at)
            VALUES (gen_random_uuid(), :s, 'Confirmed only test', true, now(), now()) RETURNING id"""), {"s": SYM})).scalar()
        await s.commit()
    yield tid
    async with ScriptSessionLocal() as s:
        await _cleanup(s)


def _wire(monkeypatch, verdicts_by_attempt):
    from app.services import research_note_service as R
    from app.services import user_errors
    calls = {"gen": 0, "held": []}
    note = {"bottom_line": "", "what_they_do": "A one. B two. C three. D four. E five.", "highlights": [], "watch": [], "risks": []}

    async def ctx(db, ticker):
        return None, None, []

    async def gen(prompt, symbol):
        calls["gen"] += 1
        return dict(note), {"model_used": "m", "input_tokens": 1, "output_tokens": 1}

    async def verify(content, filing, sections, reactions, ticker):
        bad = verdicts_by_attempt[calls["gen"] - 1]
        claims = [{"claim": t, "verdict": "unsupported" if i < bad else "supported", "reason": ""}
                  for i, t in enumerate(["A one", "B two", "C three", "D four", "E five"])]
        return {"claims": claims, "summary": {}}, "m", 1, 1

    async def none(*a, **k):
        return None

    async def held(feature, exc, symbol=None):
        calls["held"].append((feature, symbol))
    monkeypatch.setattr(R, "_fetch_context", ctx)
    monkeypatch.setattr(R, "_generate_structured", gen)
    monkeypatch.setattr(R, "_run_verification", verify)
    monkeypatch.setattr(R, "_fetch_financials", none)
    monkeypatch.setattr(R, "merger_context", none)
    monkeypatch.setattr(user_errors, "record", held)
    return calls


async def _status(tid):
    from app.database import ScriptSessionLocal
    async with ScriptSessionLocal() as s:
        return (await s.execute(text("SELECT status, error FROM research_notes WHERE ticker_id = :t"), {"t": tid})).one()


@pytest.mark.asyncio
async def test_a_note_losing_too_much_is_written_again_once_then_held_and_named(monkeypatch, ticker_id):
    from app.database import ScriptSessionLocal
    from app.services import research_note_service as R
    calls = _wire(monkeypatch, [4, 5])
    async with ScriptSessionLocal() as db:
        await R.start_research_note_generation(db, ticker_id, None)
    await R.run_research_note_background(ticker_id=ticker_id, symbol=SYM)
    st = await _status(ticker_id)
    assert calls["gen"] == 2 and st.status == R.STATUS_HELD and "more than 3" in st.error
    assert calls["held"] == [("research_note_held", SYM)]


@pytest.mark.asyncio
async def test_a_second_writing_that_passes_is_served(monkeypatch, ticker_id):
    from app.database import ScriptSessionLocal
    from app.services import research_note_service as R
    calls = _wire(monkeypatch, [4, 1])
    async with ScriptSessionLocal() as db:
        await R.start_research_note_generation(db, ticker_id, None)
    await R.run_research_note_background(ticker_id=ticker_id, symbol=SYM)
    st = await _status(ticker_id)
    assert calls["gen"] == 2 and st.status == "complete" and calls["held"] == []


@pytest.mark.asyncio
async def test_a_visitor_never_gets_a_held_note_and_gets_only_confirmed_sentences(monkeypatch, ticker_id):
    from httpx import ASGITransport, AsyncClient
    from app.database import ScriptSessionLocal
    from app.main import app
    from app.services import research_note_service as R
    _wire(monkeypatch, [1])
    async with ScriptSessionLocal() as db:
        await R.start_research_note_generation(db, ticker_id, None)
    await R.run_research_note_background(ticker_id=ticker_id, symbol=SYM)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = (await c.get("/api/v1/research-notes", params={"symbol": SYM})).json()
        assert body["structured_content"]["what_they_do"] == "B two. C three. D four. E five."
        assert {x["verdict"] for x in body["verification"]["claims"]} == {"supported"}
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE research_notes SET status = 'held' WHERE ticker_id = :t"), {"t": ticker_id})
            await s.commit()
        assert (await c.get("/api/v1/research-notes", params={"symbol": SYM})).status_code == 204


# ── the note EPS check: labeled figures are not the quarter's (production, 2026-10-28) ──

EMR = ("Adjusted diluted EPS of $1.71 excludes many items but the refund flowed through reported results, making comparability to future "
       "quarters important to monitor.")
ES = ("Excluding one-time charges, non-GAAP EPS was $0.87 in the second quarter of 2026 and $2.60 for the first half of 2026, compared with "
      "reported GAAP EPS of $0.14 in Q2 2026 versus $0.96 in Q2 2025, illustrating how significantly the charges distorted headline results.")
CBOE = "The four most recent quarters combined show diluted EPS of $12.83, up 50.6% from the $8.52 recorded in the prior four-quarter period."
EL = ("Estee Lauder has returned to profitability over the trailing four quarters, with diluted EPS of $0.50 compared to a loss of $3.15 in "
      "the prior four-quarter period. Diluted EPS of $0.24 in the March 2026 quarter was down 45.5% from $0.44 a year earlier.")
CRL = ("The trailing twelve-month loss of -$4.80 per diluted share compares to a loss of -$1.28 over the four prior quarters. The company has "
       "recorded negative or sharply declining diluted EPS in each of the last four quarters, with the December 2025 quarter seeing a loss "
       "of -$5.57 per diluted share versus -$4.17 a year earlier.")
JUNE = date(2026, 6, 30)


def test_the_note_eps_check_skips_adjusted_non_gaap_trailing_four_quarter_and_other_quarter_figures():
    strip = lambda v: {"stats": {"eps_sec": v}}
    assert eps_disagreement(strip(1.28), EMR, JUNE) is None and quarter_text_eps([EMR], JUNE) is None      # adjusted
    assert quarter_text_eps([ES], JUNE) == 0.14 and eps_disagreement(strip(0.14), ES, JUNE) is None       # non-GAAP skipped, GAAP compared
    assert eps_disagreement(strip(3.35), CBOE, JUNE) is None                                                # four quarters combined
    assert eps_disagreement(strip(-0.31), EL, JUNE) is None                                                 # trailing, and March's quarter
    assert eps_disagreement(strip(-0.03), CRL, date(2026, 6, 27)) is None                                   # trailing, and December's quarter
    assert named_quarter("Diluted EPS of $0.24 in the March 2026 quarter") == (date(2026, 3, 31), True)
    assert quarter_text_eps(["Year-to-date diluted EPS of $3.10 compares with $2.90."], JUNE) is None
    assert eps_disagreement(strip(1.50), "Diluted EPS of $1.71 for the quarter.", JUNE) == "strip EPS $1.50, text $1.71"   # unlabeled: compared
