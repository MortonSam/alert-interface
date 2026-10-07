"""The outlier check lists a quarter far below its neighbours; the dividend re-base reads only the bars and inserts nothing; the
release_eps listing is read-only and names each row's XBRL status."""
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.list_release_eps import format_rows, xbrl_status
from app.scripts.seed_dividends import CORRECTIONS, rebase_from_bars
from app.scripts.validate_data import WARN, check_eps_quarter_outliers, run_checks


@pytest.mark.asyncio
async def test_a_quarter_far_below_its_neighbours_is_listed_once():
    sym = "ZZOUT"
    try:
        async with ScriptSessionLocal() as s:
            for end, eps in (("2025-12-31", 1.0), ("2026-03-31", 0.05), ("2026-06-30", 1.2), ("2026-09-30", -0.5)):
                await s.execute(text("INSERT INTO eps_quarters (symbol, period_end, period_start, eps, filed_on, form, derived, fetched_at) VALUES (:s, :e, :e, :v, :e, '10-Q', false, now())"),
                                {"s": sym, "e": date.fromisoformat(end), "v": eps})
            await s.commit()
        r = (await run_checks([check_eps_quarter_outliers]))[0]
        assert r.level == WARN and [row for row in r.rows if row.startswith(sym)] == [f"{sym} 2026-03-31: +0.05 between +1.00 and +1.20"]
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM eps_quarters WHERE symbol = :s"), {"s": sym}); await s.commit()


@pytest.mark.asyncio
async def test_rebase_reads_the_bars_and_inserts_nothing():
    sym = "ZZRB"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Rebase Test', true)"), {"s": sym})
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2026-08-12', 'sec_rb', 100, 1, 1, 0.35, now()), (:s, '2026-05-13', 'sec_rb', 100, 1, 1, 0.35, now())"), {"s": sym})
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
                                    SELECT gen_random_uuid(), id, 'ex_dividend', d, 'x', 'yfinance', true, m::jsonb, now(), now() FROM tickers, (VALUES
                                        ('2026-08-12'::date, '{"dividend_amount": 1.4}'), ('2026-02-11'::date, '{"dividend_amount": 1.4}'), ('2026-05-13'::date, '{"dividend_amount": 0.35, "basis": "per_share"}')) v(d, m)
                                    WHERE symbol = :s"""), {"s": sym})
            await s.commit()
        await rebase_from_bars(write=False)
        mine = [c for c in CORRECTIONS if c.startswith(sym)]
        assert mine == [f"{sym} 2026-08-12: 1.4 (no basis) -> 0.35 (per_share)"]                     # the 02-11 row has no bar dividend; the 05-13 row is already per-share
        async with ScriptSessionLocal() as s:
            assert (await s.execute(text("SELECT metadata FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s) AND event_date = '2026-08-12'"), {"s": sym})).scalar() == {"dividend_amount": 1.4}
        await rebase_from_bars(write=True)
        async with ScriptSessionLocal() as s:
            rows = (await s.execute(text("SELECT event_date, metadata FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s) ORDER BY event_date"), {"s": sym})).all()
        assert [(r[0].isoformat(), r[1]) for r in rows] == [("2026-02-11", {"dividend_amount": 1.4}), ("2026-05-13", {"dividend_amount": 0.35, "basis": "per_share"}),
                                                            ("2026-08-12", {"dividend_amount": 0.35, "basis": "per_share"})]                # three rows in, three out: nothing inserted
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


def test_the_listing_names_each_rows_xbrl_status():
    base = {"symbol": "PANW", "report_date": date(2026, 9, 1), "period_end": date(2026, 7, 31), "diluted_eps_gaap": -0.35, "how": "highlights sentence", "accession": "0001327567-26-000019",
            "xbrl_eps": None, "xbrl_form": None, "difference": None, "flagged": False, "xbrl_note": None, "evidence": "GAAP net loss of $(0.35) per diluted share  \n more"}
    assert xbrl_status(base) == "awaiting XBRL"
    assert xbrl_status({**base, "xbrl_note": "derived"}) == "not comparable (XBRL derives the quarter)"
    assert xbrl_status({**base, "xbrl_eps": -0.35, "xbrl_form": "10-K"}) == "matches XBRL -0.35 (10-K)"
    assert xbrl_status({**base, "xbrl_eps": -0.46, "flagged": True}) == "FLAGGED vs XBRL -0.46"
    lines = format_rows([base])
    assert lines[0].startswith("PANW   2026-09-01  quarter ended 2026-07-31  GAAP diluted EPS -0.35  (highlights sentence; 8-K 0001327567-26-000019)  awaiting XBRL")
    assert lines[1] == "       evidence: GAAP net loss of $(0.35) per diluted share more"
