"""Fail closed: a validate failure on a fact for a ticker hides every surface that uses it until the check passes, and the digest lists it."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.validate_data import ERROR, PASS, check_estimate_beside_confirmed, check_next_dividend_amount, outcome_fields, run_checks, write_holds
from app.services import ask_ivy as A
from app.services import briefing_build as BB
from app.services.fact_holds import FACTS, FACT_OF_CHECK, SURFACES, hidden_lines, holds_from_results, symbol_of_row
from app.services.notify import digest_message


def test_holds_come_from_the_mapped_error_checks_and_name_real_tickers():
    results = [SimpleNamespace(name="next_dividend_amount", level=ERROR, rows=["PCAR 2026-11-11: stored 1.4 with no per-payment basis (no basis) vs last paid 0.35", "Only 3 shown"]),
               SimpleNamespace(name="estimate_beside_confirmed", level=ERROR, rows=["FDX: estimate 2026-10-12 beside confirmed 2026-10-28"]),
               SimpleNamespace(name="pe_sanity", level="warn", rows=["TSLA: P/E 352 on trailing EPS 1.08"]),                 # a warning holds nothing
               SimpleNamespace(name="chain_coverage", level=ERROR, rows=["MU  no fresh chain"])]                           # not a per-ticker fact check
    holds = holds_from_results(results, {"PCAR", "FDX", "TSLA", "MU"})
    assert [(h["symbol"], h["fact"], h["check"]) for h in holds] == [("FDX", "report_date", "estimate_beside_confirmed"), ("PCAR", "dividend_amount", "next_dividend_amount")]
    assert hidden_lines(holds) == ["FDX: report date (estimate_beside_confirmed)", "PCAR: dividend amount (next_dividend_amount)"]
    assert symbol_of_row("BRK-B: x") == "BRK-B" and symbol_of_row("only 3 shown") is None and symbol_of_row("Every stored upcoming dividend ...") is None
    assert set(FACT_OF_CHECK.values()) <= set(FACTS) and set(SURFACES) == set(FACTS)
    body = digest_message("2026-10-08", 30, 30, [], None, 90.0, None, hidden=hidden_lines(holds))[1]
    assert "hidden until validate passes (2): FDX: report date (estimate_beside_confirmed); PCAR: dividend amount (next_dividend_amount)" in body
    assert "hidden" not in digest_message("2026-10-08", 30, 30, [], None, 90.0, None)[1]
    assert outcome_fields([], holds)["hidden_count"] == 2


@pytest.mark.asyncio
async def test_a_failing_dividend_amount_and_a_failing_report_date_hide_their_surfaces():
    sym = "ZZHOLD"
    today = date.today()
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, sector) VALUES (gen_random_uuid(), :s, 'Hold Test, Inc.', true, 'Industrials')"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, :d, 'sec_zh', 100, 1, 1, 0.25, now())"),
                            {"s": sym, "d": today - timedelta(days=80)})
            # an upcoming ex-dividend with the annual rate stored, and an estimate beside a company-confirmed date for the same report
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at) VALUES
                (gen_random_uuid(), :t, 'ex_dividend', :xd, 'x', 'yfinance', true, '{"dividend_amount": 1.0, "basis": "annual_rate"}', now(), now()),
                (gen_random_uuid(), :t, 'earnings', :est, 'x', 'yfinance', false, '{}', now(), now()),
                (gen_random_uuid(), :t, 'earnings', :con, 'x', 'edgar', true, '{}', now(), now())"""),
                {"t": tid, "xd": today + timedelta(days=5), "est": today + timedelta(days=6), "con": today + timedelta(days=9)})
            await s.commit()
        results = await run_checks([check_next_dividend_amount, check_estimate_beside_confirmed])
        assert all(r.level == ERROR for r in results)
        holds = await write_holds(results)
        mine = {(h["fact"], h["check"]) for h in holds if h["symbol"] == sym}
        assert mine == {("dividend_amount", "next_dividend_amount"), ("report_date", "estimate_beside_confirmed")}
        async with ScriptSessionLocal() as db:
            qs = await BB.build_questions(db, sym, today, all_candidates=True)
            brief = await BB.build_briefing(db, sym, today)
            pack = await A.fact_pack(db, sym, today)
            from httpx import ASGITransport, AsyncClient
            from app.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                soon = (await c.get("/api/v1/discover/reporting-soon?days=14&limit=50")).json()
        assert "ex_dividend" not in [q["key"] for q in qs["questions"]]                                      # the dividend question is gone
        assert not any("Reports" in s2["text"] for s2 in brief["sentences"])                                   # no next-report clause in the Overview
        assert not any(f["id"].startswith(("next_", "ex_dividend", "dividend")) for f in pack["facts"]), [f["id"] for f in pack["facts"]]
        assert sym not in [i["symbol"] for i in soon["items"]]                                                 # off the Discover list
        # the check passes again: the holds clear and the surfaces return
        async with ScriptSessionLocal() as s:
            await s.execute(text("""UPDATE events SET metadata = '{"dividend_amount": 0.25, "basis": "per_share"}' WHERE ticker_id = :t AND event_type = 'ex_dividend'"""), {"t": tid})
            await s.execute(text("DELETE FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND NOT is_confirmed"), {"t": tid})
            await s.commit()
        holds = await write_holds(await run_checks([check_next_dividend_amount, check_estimate_beside_confirmed]))
        assert not any(h["symbol"] == sym for h in holds)
        async with ScriptSessionLocal() as db:
            qs = await BB.build_questions(db, sym, today, all_candidates=True)
            brief = await BB.build_briefing(db, sym, today)
        assert "ex_dividend" in [q["key"] for q in qs["questions"]] and any("Reports" in s2["text"] for s2 in brief["sentences"])
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM fact_holds WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
