"""The implied move appears only against a company-confirmed report date: the strip question, the Overview clause, Ask Ivy's
facts and the Discover comparison are all absent on an estimated date (FDX's Oct 12, 2026 estimate priced a report FedEx had
moved to Oct 28)."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.database import ScriptSessionLocal
from app.services import ask_ivy as A
from app.services import briefing_build as BB
from app.services.next_earnings import NextEarnings


def _fake_implied(pct=0.035):
    async def fake(db, sym, spot, min_date, today):
        return {"implied_pct": pct, "chain_date": today, "expiration": min_date + timedelta(days=2)}
    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation,shown", [("estimated", False), ("expected_unconfirmed", False), ("confirmed", True)])
async def test_strip_overview_and_ask_ivy_price_only_a_confirmed_date(monkeypatch, confirmation, shown):
    today = date.today() + timedelta(days=60)          # past MU's post-report window, so the Overview takes its "upcoming" branch
    async def fake_next(db, ticker_id, when):
        return NextEarnings(date=when + timedelta(days=10), source="yfinance" if confirmation != "confirmed" else "edgar", confirmation=confirmation, note="x")
    monkeypatch.setattr(BB, "next_earnings_for", fake_next)
    monkeypatch.setattr(BB, "_implied", _fake_implied())
    async with ScriptSessionLocal() as db:
        qs = await BB.build_questions(db, "MU", today)
        brief = await BB.build_briefing(db, "MU", today)
        pack = await A.fact_pack(db, "MU", today)
    assert ("implied_big" in [q["key"] for q in qs["questions"]]) is shown, [q["key"] for q in qs["questions"]]
    assert any("options price a move" in s["text"] for s in brief["sentences"]) is shown, [s["text"] for s in brief["sentences"]]
    assert any(f["id"] in ("implied_vs_typical", "implied_move") for f in pack["facts"]) is shown, [f["id"] for f in pack["facts"]]


@pytest.mark.asyncio
async def test_discover_comparison_skips_an_estimated_date(monkeypatch):
    from app.routers.discover import _batch_move_comparison
    monkeypatch.setattr(BB, "_implied", _fake_implied())
    today = date.today()
    cond = {"MU": {"total": 20, "avg_abs_1d": 5.0}}
    est = [SimpleNamespace(symbol="MU", event_date=today + timedelta(days=5), is_confirmed=False, unresolved_since=None)]
    con = [SimpleNamespace(symbol="MU", event_date=today + timedelta(days=5), is_confirmed=True, unresolved_since=None)]
    async with ScriptSessionLocal() as db:
        assert await _batch_move_comparison(db, est, cond, today) == {}
        got = await _batch_move_comparison(db, con, cond, today)
    assert got["MU"]["implied_move_pct"] == 3.5 and got["MU"]["typical_move_pct"] == 5.0
