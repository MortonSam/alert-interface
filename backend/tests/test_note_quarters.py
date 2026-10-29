"""A note's inputs name one latest quarter, or it is not served and the new note waits (Sam, 2026-10-29, GOOG): the note written the
night after Alphabet's Oct 28 report stated the new quarter's $2.12 diluted EPS from the 10-Q filed Oct 29 while its strip still
showed the July quarter. The queue covers the largest companies first."""
import json
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import generate_notes as G
from app.services import note_quarters as NQ

pytestmark = pytest.mark.xdist_group(name="note_quarters")

GOOG = {"strip": "2026-07-22", "eps": "2026-10-28", "filing": "2026-10-28"}


def test_inputs_naming_different_quarters_disagree():
    assert NQ.disagreement(GOOG) == "strip 2026-07-22, eps 2026-10-28, filing 2026-10-28"
    assert NQ.disagreement({**GOOG, "strip": "2026-10-28"}) is None
    assert NQ.disagreement({"strip": None, "eps": "2026-10-28", "filing": "2026-10-28"}) is None       # an unread input never disagrees
    assert NQ.disagreement(None) is None


def test_a_filing_belongs_to_the_report_just_before_it():
    reports = [date(2026, 4, 23), date(2026, 7, 22), date(2026, 7, 23), date(2026, 10, 28)]
    assert NQ.filing_quarter("2026-10-29", reports) == date(2026, 10, 28)        # Alphabet's 10-Q, the day after its release
    assert NQ.filing_quarter("2026-07-24", reports) == date(2026, 7, 23)
    assert NQ.filing_quarter("2026-09-30", reports) is None                     # no report within FILING_AFTER_REPORT_DAYS before it
    assert NQ.FILING_AFTER_REPORT_DAYS == 45


def test_the_queue_puts_missing_and_hidden_notes_first_largest_first():
    rows = [("SMALL", None, False, None, 10e9, False, False), ("TSLA", "complete", False, 1, 1.4e12, True, False),
            ("GOOG", "complete", False, 2, 3.9e12, False, True), ("MID", None, False, None, 80e9, False, False),
            ("OLD", "complete", False, 1, 2e12, False, False), ("NEW", "complete", True, 2, 5e12, False, False),
            ("OK", "complete", False, 2, 6e12, False, False)]
    assert G.queue(rows, 170) == ["GOOG", "TSLA", "MID", "SMALL", "OLD", "NEW"]
    assert G.due_kind("complete", False, 2, False, True) == (0, "write") and G.due_kind("complete", False, 1, True, False) == (0, "recheck")
    assert G.due_kind("complete", False, 2, False, False) is None


async def _seed(s, sym: str, reaction_dates: list[str]):
    await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, market_cap) VALUES (gen_random_uuid(), :s, 'Quarter Test', true, 1) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
    tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
    for d, eps in (("2026-07-22", None), ("2026-10-28", 2.12)):
        await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, is_confirmed, eps_actual, created_at, updated_at)
            VALUES (gen_random_uuid(), :t, 'earnings', :d, 'Earnings', true, :e, now(), now())"""), {"t": tid, "d": date.fromisoformat(d), "e": eps})
    for d in reaction_dates:
        await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, outcome, computation_version)
            VALUES (gen_random_uuid(), :t, 'earnings', :d, 1.0, 'unknown', 3)"""), {"t": tid, "d": date.fromisoformat(d)})
    sc = {"what_they_do": "It sells search ads.", "bottom_line": "Claim x.", "highlights": [], "watch": [], "risks": [], "stats": {"latest_quarter_date": "2026-07-22"}}
    ver = {"version": 2, "claims": [{"claim": "It sells search ads.", "verdict": "supported", "reason": "Item 1", "sentence": "It sells search ads."}],
           "summary": {"supported": 1, "unsupported": 0, "contradicted": 0}}
    await s.execute(text("""INSERT INTO research_notes (id, ticker_id, generated_at, source_filings, content, model_used, input_tokens, output_tokens, status,
        verification, verified_at, structured_content, created_at, updated_at)
        VALUES (gen_random_uuid(), :t, :g, CAST(:f AS jsonb), 'It sells search ads.', 'm', 1, 1, 'complete', CAST(:v AS jsonb), :g, CAST(:sc AS jsonb), now(), now())"""),
        {"t": tid, "g": datetime(2026, 10, 29, 8, 44, tzinfo=timezone.utc), "f": json.dumps([{"form_type": "10-Q", "accession_number": "0001652044-26-000084", "filing_date": "2026-10-29", "url": "https://www.sec.gov/x"}]),
         "v": json.dumps(ver), "sc": json.dumps(sc)})
    await s.commit()
    return tid


async def _clean(s, sym: str):
    for t in ("research_notes", "historical_reactions", "events"):
        await s.execute(text(f"DELETE FROM {t} WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
    await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
    await s.commit()


@pytest.mark.asyncio
async def test_googs_note_is_never_served_while_its_inputs_name_different_quarters():
    from app.main import app
    from app.models.research_note import ResearchNote
    from sqlalchemy import select
    sym = "ZZGOOQ"
    async with ScriptSessionLocal() as s:
        try:
            await _clean(s, sym)
            tid = await _seed(s, sym, ["2026-07-22"])
            note = (await s.execute(select(ResearchNote).where(ResearchNote.ticker_id == tid))).scalar_one()
            assert await NQ.note_inputs(s, note) == GOOG                   # inferred: the strip, the 10-Q's report, the latest actual
            assert await NQ.withheld_now(s, note)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                assert (await c.get("/api/v1/research-notes", params={"symbol": sym})).status_code == 204
            # a note written once every input has the new quarter is served
            await s.execute(text("UPDATE research_notes SET structured_content = jsonb_set(structured_content, '{inputs}', CAST(:i AS jsonb)) WHERE ticker_id = :t"),
                            {"i": json.dumps({k: "2026-10-28" for k in NQ.KEYS}), "t": tid})
            await s.commit()
            s.expire_all()
            note = (await s.execute(select(ResearchNote).where(ResearchNote.ticker_id == tid))).scalar_one()
            assert not await NQ.withheld_now(s, note)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                assert (await c.get("/api/v1/research-notes", params={"symbol": sym})).status_code == 200
        finally:
            await _clean(s, sym)


@pytest.mark.asyncio
async def test_a_new_note_waits_until_the_strip_has_the_new_quarter(monkeypatch):
    sym = "ZZGOOW"

    class Edgar:
        async def get_cik(self, s):
            return "0001652044"

        async def get_best_filing(self, cik):
            return {"form_type": "10-Q", "filing_date": "2026-10-29"}
    async with ScriptSessionLocal() as s:
        try:
            await _clean(s, sym)
            tid = await _seed(s, sym, ["2026-07-22"])
            why = await G.write_waits(Edgar(), sym, date(2026, 10, 29))
            assert why == "waiting: the inputs name different quarters (strip 2026-07-22, eps 2026-10-28, filing 2026-10-28)"
            await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, outcome, computation_version)
                VALUES (gen_random_uuid(), :t, 'earnings', '2026-10-28', -1.0, 'unknown', 3)"""), {"t": tid})
            await s.commit()
            assert await G.write_waits(Edgar(), sym, date(2026, 11, 5)) is None          # every input names Oct 28: the note is written
            assert await NQ.current_inputs(s, tid, "2026-10-29", date(2026, 11, 5)) == {k: "2026-10-28" for k in NQ.KEYS}
        finally:
            await _clean(s, sym)


def test_the_nightly_budget_under_the_35_dollar_cap_and_the_nov_15_reminder():
    from app.services import ai_spend as A
    assert A.notes_night_budget(35.0, walkthroughs_live=False) == 30.0          # until the walkthrough nightly is live
    assert A.notes_night_budget(35.0, walkthroughs_live=True) == 16.0           # then notes 16, walkthroughs 14, visitors at least 5
    assert A.WALKTHROUGHS_NIGHT_USD == 14.0 and A.VISITOR_RESERVE_USD == 5.0
    assert A.notes_night_budget(20.0, walkthroughs_live=False) == 15.0          # back at $20: visitors still keep 5
    assert A.notes_night_budget(20.0, walkthroughs_live=True) == 1.0
    assert A.cap_reminders(date(2026, 11, 14), 35.0) == []
    assert A.cap_reminders(date(2026, 11, 15), 35.0) == ["set AI_DAILY_SPEND_CAP_USD back to $20 on Railway (raised to $35 until Nov 15, 2026)"]
    assert A.cap_reminders(date(2026, 11, 20), 20.0) == []                       # clears itself once the cap is back
    assert not A.walkthroughs_live()                                            # main has no walkthrough step yet
