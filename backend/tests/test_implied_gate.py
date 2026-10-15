"""The implied move appears only against a company-confirmed report date: the strip question, the Overview clause, Ask Ivy's
facts and the Discover comparison are all absent on an estimated date (FDX's Oct 12, 2026 estimate priced a report FedEx had
moved to Oct 28)."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import ask_ivy as A
from app.services import briefing_build as BB
from app.services.next_earnings import NextEarnings


def _fake_view():
    from app.services import report_move as RM
    from app.services.move_comparison import report_sentence
    async def fake(db, sym, report_date, today=None, held_facts=(), typical=None):
        rm = RM.ReportMove(RM.OK, pct=0.035, e=0.035 / 0.8, t2_years=0.05, before=RM.Leg("2026-10-16", today.isoformat(), 1.0, 0.3),
                           after=RM.Leg("2026-10-23", today.isoformat(), 1.0, 0.5), report_date=str(report_date), method=RM.PAIR)
        return {"state": RM.OK, "move": rm, "report_move": rm.as_dict(), "pct": 0.035, "rep": 3.5, "chain_date": today, "typical_move_pct": 5.0,
                "typical_n": 20, "move_comparison": "less than usual", "comparison": report_sentence(3.5, 5.0, "less than usual", today)}
    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation,shown", [("estimated", False), ("expected_unconfirmed", False), ("confirmed", True)])
async def test_strip_overview_and_ask_ivy_price_only_a_confirmed_date(monkeypatch, confirmation, shown):
    async with ScriptSessionLocal() as db:             # pinned past MU's latest stored report and its reaction window, so the Overview takes its "upcoming" branch
        latest = (await db.execute(text("SELECT max(e.event_date) FROM events e JOIN tickers t ON t.id = e.ticker_id "
                                         "WHERE t.symbol = 'MU' AND e.event_type = 'earnings'"))).scalar()
    today = max(latest or date.today(), date.today()) + timedelta(days=20)
    async def fake_next(db, ticker_id, when):
        return NextEarnings(date=when + timedelta(days=10), source="yfinance" if confirmation != "confirmed" else "edgar", confirmation=confirmation, note="x")
    monkeypatch.setattr(BB, "next_earnings_for", fake_next)
    monkeypatch.setattr(BB, "report_move_view", _fake_view())
    async with ScriptSessionLocal() as db:
        qs = await BB.build_questions(db, "MU", today)
        brief = await BB.build_briefing(db, "MU", today)
        pack = await A.fact_pack(db, "MU", today)
    assert ("implied_big" in [q["key"] for q in qs["questions"]]) is shown, [q["key"] for q in qs["questions"]]
    assert any("Options price a move" in s["text"] for s in brief["sentences"]) is shown, [s["text"] for s in brief["sentences"]]
    assert any(f["id"] in ("implied_vs_typical", "report_move", "report_move_sentence") for f in pack["facts"]) is shown, [f["id"] for f in pack["facts"]]


@pytest.mark.asyncio
async def test_discover_comparison_skips_an_estimated_date(monkeypatch):
    from app.routers.discover import _batch_move_comparison
    from app.services import report_move as RM
    async def fake(db, sym, report_date, today=None):
        return RM.ReportMove(RM.OK, pct=0.035, e=0.035 / 0.8, t2_years=0.05, before=RM.Leg("2026-10-16", today.isoformat(), 1.0, 0.3),
                             after=RM.Leg("2026-10-23", today.isoformat(), 1.0, 0.5), report_date=str(report_date))
    monkeypatch.setattr(RM, "report_move", fake)
    today = date.today()
    cond = {"MU": {"total": 20, "avg_abs_1d": 5.0}}
    est = [SimpleNamespace(symbol="MU", event_date=today + timedelta(days=5), is_confirmed=False, unresolved_since=None)]
    con = [SimpleNamespace(symbol="MU", event_date=today + timedelta(days=5), is_confirmed=True, unresolved_since=None)]
    async with ScriptSessionLocal() as db:
        assert await _batch_move_comparison(db, est, cond, today) == {}
        got = await _batch_move_comparison(db, con, cond, today)
    assert got["MU"]["report_move_pct"] == 3.5 and got["MU"]["typical_move_pct"] == 5.0
