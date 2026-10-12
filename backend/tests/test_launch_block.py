"""The launch block of 2026-10-12: the courier retired from customer-facing data, the chart's intraday periods and two internal prices
off Yahoo, the dead-man alert, Fable 5 priced, one site-wide AI spend cap, a 204 for a ticker without a note, and the name shortener."""
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import refresh
from app.scripts.compute_put_call import PUT_CALL_COMPUTATION_VERSION, nearest_expiration, ratio_from
from app.scripts.validate_data import CHECKS, check_put_call_fresh
from app.services import ai_spend, options_source as O, price_bars
from app.services.briefing import short_name
from app.services.research_cost import PRICES_USD_PER_MTOK, estimate_cost_usd

pytestmark = pytest.mark.xdist_group(name="launch_block")
ROOT = Path(__file__).resolve().parents[1]


def test_pages_read_intrinio_only_and_the_courier_stays_a_shadow():
    assert O.order("intrinio") == ["intrinio"] and O.order("courier") == ["intrinio"]
    admin = (ROOT / "app" / "routers" / "admin.py").read_text()
    assert "INSERT INTO put_call_snapshots" not in admin and "put_chain(db, sym, item.expiration, chain_dict, chain_store.COURIER)" in admin   # chains still ingested for the shadow
    assert "intrinio_chain:%" in (ROOT / "app" / "routers" / "system.py").read_text()      # the home counter counts the serving source's chains


def test_the_put_call_ratio_is_a_nightly_intrinio_step_at_version_3():
    assert PUT_CALL_COMPUTATION_VERSION == 3 and check_put_call_fresh in CHECKS
    labels = [label for label, _ in refresh.STEPS]
    assert labels.index("Put/call ratio (Intrinio)") > labels.index("Options chains (Intrinio)")
    assert nearest_expiration(["2026-10-09", "2026-10-16", "2026-10-23"], "2026-10-09") == "2026-10-16" and nearest_expiration(["2026-10-09"], "2026-10-09") is None
    calls = [{"volume": 300}, {"volume": None}, {"volume": 200}]
    puts = [{"volume": 600}, {"volume": 150}]
    assert ratio_from(calls, puts) == (1.5, 750, 500)
    assert ratio_from([{"volume": 1}], puts)[0] is None                                   # a side too thin: the totals stay, the ratio is null


def test_the_chart_and_the_internal_prices_no_longer_read_yahoo():
    for path in ("app/routers/tickers.py", "app/routers/thesis.py", "app/scripts/snapshot_iv.py"):
        assert "YFinanceClient" not in (ROOT / path).read_text(), path
    assert "intraday_chart(sym, session, prev_close, start=" in (ROOT / "app" / "routers" / "tickers.py").read_text()
    rv = price_bars.realized_vol_sync("AAPL")
    assert rv["status"] in ("ok", "insufficient", "no_data") and ("current_rv" in rv and "pct_change_20d" in rv)
    assert price_bars.last_close_sync("AAPL") is None or price_bars.last_close_sync("AAPL") > 0


def test_fable_5_is_priced_so_draft_spend_counts():
    assert PRICES_USD_PER_MTOK["claude-fable-5"] == (10.0, 50.0)
    assert estimate_cost_usd("claude-fable-5", 12000, 1500) == round(12000 * 10 / 1e6 + 1500 * 50 / 1e6, 4)


def test_the_site_wide_ai_cap_resets_at_midnight_new_york():
    assert ai_spend.spend_day(datetime(2026, 10, 13, 3, 30, tzinfo=timezone.utc)) == "2026-10-12"      # 23:30 ET on the 12th
    assert ai_spend.spend_day(datetime(2026, 10, 13, 4, 30, tzinfo=timezone.utc)) == "2026-10-13"
    assert ai_spend.reached(20.0, 20.0) and not ai_spend.reached(19.99, 20.0) and ai_spend.cap_usd() == 20.0


@pytest.mark.asyncio
async def test_every_feature_adds_to_one_ledger_and_the_cap_closes_each_with_its_own_message():
    now = datetime(2030, 1, 5, 15, 0, tzinfo=timezone.utc)        # a day no real spend touches
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :p"), {"p": "ai_spend%:2030-01-05"})
            await s.commit()
            await ai_spend.add(s, 0.12, now)
            await ai_spend.add(s, 0.003, now)
            await ai_spend.add(s, None, now)
            assert round(await ai_spend.spend_today(s, now), 3) == 0.123 and await ai_spend.unpriced_today(s, now) == 1
            summary = await ai_spend.summary(s, now)
            assert summary["day"] == "2030-01-05" and summary["cap_usd"] == 20.0 and summary["reached"] is False
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :p"), {"p": "ai_spend%:2030-01-05"})
            await s.commit()
    src = (ROOT / "app" / "routers").glob("*.py")
    joined = "".join(p.read_text() for p in src)
    assert joined.count("ai_spend.cap_reached(db)") == 3          # notes, drafts, Ask Ivy
    assert "detail=DRAFT_POLICY.global_message" in joined and "RESEARCH_GENERATION_POLICY.global_message.format" in joined


def test_the_dead_man_alert_fires_two_hours_after_the_start_with_no_finished_run():
    spec = importlib.util.spec_from_file_location("check_digest", ROOT / "ops" / "deadman" / "check_digest.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    ny = m.CLOCK
    done = {"step_outcomes": {"Nightly run": {"slot": "2026-10-12", "started_at": "2026-10-12T06:30:16+00:00", "finished_at": "2026-10-12T07:58:44+00:00"}}}
    missed = {"step_outcomes": {"Nightly run": {"slot": "2026-10-11", "finished_at": "2026-10-11T07:57:42+00:00"}}}
    stuck = {"step_outcomes": {"Nightly run": {"slot": "2026-10-12", "started_at": "2026-10-12T06:30:16+00:00"}}}
    at = lambda h, mi: datetime(2026, 10, 12, h, mi, tzinfo=ny)
    assert m.digest_late(missed, at(4, 15)) == (False, "before the 04:30 New York deadline")
    assert m.digest_late(done, at(4, 45))[0] is False
    late, why = m.digest_late(missed, at(4, 45))
    assert late and why.startswith("no nightly run for 2026-10-12")
    assert m.digest_late(stuck, at(4, 45))[0] and m.digest_late(None, at(4, 45)) == (True, "/health could not be read")
    plist = (ROOT / "ops" / "deadman" / "com.alertinterface.deadman.plist").read_text()
    assert "check_digest.py" in plist and "NTFY" not in plist


@pytest.mark.asyncio
async def test_a_ticker_without_a_note_answers_204_not_404():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with ScriptSessionLocal() as s:
        sym = (await s.execute(text("""SELECT t.symbol FROM tickers t LEFT JOIN research_notes r ON r.ticker_id = t.id WHERE r.id IS NULL AND t.is_active ORDER BY t.symbol LIMIT 1"""))).scalar()
    if not sym:
        pytest.skip("every active ticker has a note in this database")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get(f"/api/v1/research-notes?symbol={sym}")).status_code == 204


def test_the_name_shortener_never_ends_on_an_ampersand():
    assert short_name("JPMorgan Chase & Co.") == "JPMorgan Chase"
    assert short_name("Johnson & Johnson") == "Johnson & Johnson" and short_name("Procter & Gamble Company") == "Procter & Gamble"
