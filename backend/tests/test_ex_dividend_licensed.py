"""A forward ex-dividend date from Yahoo is personal-use data: with PERSONAL_USE_DATA_SHOWN off the question strip never asks about it
(AES's "Estimated, as of Oct 13, 2026", 2026-10-26), as Catalysts already filters it (personal_use.withheld_event); a date from a
licensed source still asks."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.config import settings
from app.database import ScriptSessionLocal
from app.services import briefing_build as BB

pytestmark = pytest.mark.xdist_group(name="shared_rows")


@pytest.mark.asyncio
async def test_a_yahoo_ex_dividend_date_asks_nothing_while_personal_use_data_is_held(monkeypatch):
    sym, today = "ZZXDIV", date.today()
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, sector) VALUES (gen_random_uuid(), :s, 'Dividend Test, Inc.', true, 'Utilities')"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at) VALUES
                (gen_random_uuid(), :t, 'ex_dividend', :xd, 'x', 'yfinance', true, '{"dividend_amount": 0.18, "basis": "per_share"}', now(), now())"""),
                {"t": tid, "xd": today + timedelta(days=5)})
            await s.commit()
        monkeypatch.setattr(settings, "personal_use_data_shown", False)
        async with ScriptSessionLocal() as db:
            qs = await BB.build_questions(db, sym, today, all_candidates=True)
        assert "ex_dividend" not in [q["key"] for q in qs["questions"]]
        assert not any("Estimated, as of" in str(q) for q in qs["questions"])
        monkeypatch.setattr(settings, "personal_use_data_shown", True)
        async with ScriptSessionLocal() as db:
            qs = await BB.build_questions(db, sym, today, all_candidates=True)
        assert "ex_dividend" in [q["key"] for q in qs["questions"]]
        async with ScriptSessionLocal() as s:                     # a licensed source asks with the flag off
            await s.execute(text("UPDATE events SET source = 'edgar' WHERE ticker_id = :t AND event_type = 'ex_dividend'"), {"t": tid})
            await s.commit()
        monkeypatch.setattr(settings, "personal_use_data_shown", False)
        async with ScriptSessionLocal() as db:
            qs = await BB.build_questions(db, sym, today, all_candidates=True)
        assert "ex_dividend" in [q["key"] for q in qs["questions"]]
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
