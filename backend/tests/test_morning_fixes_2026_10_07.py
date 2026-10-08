"""The Oct 7 nightly's morning fixes: stale forward dividend rows are retired, validate's range checks judge the latest snapshot,
void picks have their own check and are never priced, the digest counts voids and already-voids apart, and a release figure
whose XBRL quarter is only derived is recorded as not comparable rather than overdue."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.event import Event
from app.models.ticker import Ticker
from app.scripts.seed_dividends import FORWARD_BASIS_INTRINIO, FORWARD_BASIS_UNKNOWN, PER_PAYMENT_BASES, retire_stale_forward_rows
from app.scripts.validate_data import (CHECKS, ERROR, PASS, WARN, check_pick_lifecycle, check_pick_void, check_release_eps_checked, check_sector_peer_avg_range,
                                       check_sector_peer_sector_avg_range, run_checks)
from app.services.notify import digest_message


async def _ticker(s, sym, name, sector=None):
    await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, sector) VALUES (gen_random_uuid(), :s, :n, true, :sec)"), {"s": sym, "n": name, "sec": sector})
    return (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one()


async def _cleanup(sym):
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
        await s.execute(text("DELETE FROM alert_picks WHERE symbol = :s"), {"s": sym})
        await s.execute(text("DELETE FROM sector_peer_snapshots WHERE symbol = :s"), {"s": sym})
        await s.execute(text("DELETE FROM release_eps WHERE symbol = :s"), {"s": sym})
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
        await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
        await s.commit()


@pytest.mark.asyncio
async def test_stale_forward_dividend_rows_are_dropped_rebased_or_unpriced():
    """PCAR's shape: the old writer's 2026-11-11 row holds the annual rate 1.40 with no basis beside the declared 11-10 row at 0.35."""
    sym = "ZZSTALE"
    today = date.today()
    try:
        async with ScriptSessionLocal() as s:
            t = await _ticker(s, sym, "Stale Forward, Inc.")
            for d, meta in ((today + timedelta(days=35), {"dividend_amount": 1.4}),                                    # the old writer: annual rate, no basis, a date yfinance no longer reports
                            (today + timedelta(days=34), {"dividend_amount": 0.35, "basis": FORWARD_BASIS_INTRINIO}),  # the declared date, already per-payment
                            (today + timedelta(days=60), {"dividend_amount": 9.9, "basis": "declared_8k", "declared": True}),   # declared: never touched
                            (today - timedelta(days=50), {"dividend_amount": 1.4})):                                   # past: not a forward row
                s.add(Event(ticker_id=t.id, event_type="ex_dividend", event_date=d, title="x", source="yfinance", is_confirmed=True, metadata_=meta))
            await s.commit()
        async with ScriptSessionLocal() as s:
            t = (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one()
            out = await retire_stale_forward_rows(s, t, today + timedelta(days=34), 0.35, today)
            await s.commit()
            rows = (await s.execute(text("SELECT event_date, metadata FROM events WHERE ticker_id = :t ORDER BY event_date"), {"t": t.id})).all()
        assert out == {"dropped": 1, "rebased": 0, "unpriced": 0}
        assert [(r[0] - today).days for r in rows] == [-50, 34, 60]                                  # the 11-11 row is gone; the declared and the past rows stand
        assert rows[1][1] == {"dividend_amount": 0.35, "basis": FORWARD_BASIS_INTRINIO} and rows[2][1]["declared"] is True
        # no date declared today: a no-basis row on its own date is re-based to the bars' last payment, or loses its amount when the bars hold none
        async with ScriptSessionLocal() as s:
            t = (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one()
            s.add(Event(ticker_id=t.id, event_type="ex_dividend", event_date=today + timedelta(days=20), title="x", source="yfinance", is_confirmed=True, metadata_={"dividend_amount": 4.64}))
            await s.commit()
            assert await retire_stale_forward_rows(s, t, None, 1.16, today) == {"dropped": 0, "rebased": 1, "unpriced": 0}
            await s.commit()
            meta = await s.scalar(text("SELECT metadata FROM events WHERE ticker_id = :t AND event_date = :d"), {"t": t.id, "d": today + timedelta(days=20)})
            assert meta == {"dividend_amount": 1.16, "basis": FORWARD_BASIS_INTRINIO}
            await s.execute(text("UPDATE events SET metadata = '{\"dividend_amount\": 4.64}' WHERE ticker_id = :t AND event_date = :d"), {"t": t.id, "d": today + timedelta(days=20)})
            await s.commit()
            assert await retire_stale_forward_rows(s, t, None, None, today) == {"dropped": 0, "rebased": 0, "unpriced": 1}
            await s.commit()
            meta = await s.scalar(text("SELECT metadata FROM events WHERE ticker_id = :t AND event_date = :d"), {"t": t.id, "d": today + timedelta(days=20)})
            assert meta == {"basis": FORWARD_BASIS_UNKNOWN} and FORWARD_BASIS_UNKNOWN not in PER_PAYMENT_BASES
            assert await retire_stale_forward_rows(s, t, None, None, today) == {"dropped": 0, "rebased": 0, "unpriced": 0}   # idempotent
    finally:
        await _cleanup(sym)


def test_no_module_reads_the_annualized_dividend_rate():
    """The only forward-dividend writer is seed_dividends, and nothing under app/ reads yfinance's dividendRate."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py") if "dividendRate" in p.read_text() and p.name != "seed_dividends.py"]
    assert offenders == []
    src = (root / "scripts/seed_dividends.py").read_text()
    assert "info.get(\"dividendRate\")" not in src and "lastDividendValue" in src
    writers = [str(p.relative_to(root)) for p in root.rglob("*.py") if "EventType.EX_DIVIDEND" in p.read_text() and "session.add(Event(" in p.read_text()]
    assert writers == ["scripts/seed_dividends.py"]


@pytest.mark.asyncio
async def test_sector_peer_range_checks_judge_the_latest_row_only():
    """VMRK's shape: an old snapshot row at 0.01 under a later row at 2.19 is history, not an error; a latest row at 0.01 is."""
    sym = "ZZPEER"
    try:
        async with ScriptSessionLocal() as s:
            await _ticker(s, sym, "Peer Test", "Real Estate")
            for d, avg, n in ((date(2026, 10, 1), 0.01, 1), (date(2026, 10, 6), 2.19, 20)):
                await s.execute(text("""INSERT INTO sector_peer_snapshots (id, sector, symbol, avg_abs_1d, quarter_count, sector_avg_abs_1d, sector_peer_count, as_of_date, computation_version, created_at)
                                        VALUES (gen_random_uuid(), 'ZZ Sector', :s, :a, :n, 3.07, 9, :d, 1, now())"""), {"s": sym, "a": avg, "n": n, "d": d})
            await s.commit()
        r = (await run_checks([check_sector_peer_avg_range]))[0]
        assert not any(sym in row for row in r.rows), r.rows
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE sector_peer_snapshots SET avg_abs_1d = 0.01 WHERE symbol = :s AND as_of_date = '2026-10-06'"), {"s": sym})
            await s.commit()
        r = (await run_checks([check_sector_peer_avg_range]))[0]
        assert r.level == ERROR and any(row.startswith(f"{sym}  avg_abs_1d=0.01 (as of 2026-10-06, 20 reports)") for row in r.rows)
        async with ScriptSessionLocal() as s:                                 # the sector aggregate likewise: only the sector's latest row
            await s.execute(text("UPDATE sector_peer_snapshots SET sector_avg_abs_1d = 0.2 WHERE symbol = :s AND as_of_date = '2026-10-01'"), {"s": sym})
            await s.commit()
        r = (await run_checks([check_sector_peer_sector_avg_range]))[0]
        assert not any("ZZ Sector" in row for row in r.rows)
    finally:
        await _cleanup(sym)


@pytest.mark.asyncio
async def test_void_picks_leave_the_lifecycle_check_and_have_their_own():
    sym = "ZZLIFE"
    try:
        async with ScriptSessionLocal() as s:
            await _ticker(s, sym, "Lifecycle Test")
            for status, reason, at, close_price in (("void", "Report came 17 sessions after entry", datetime(2026, 10, 7, 6, tzinfo=timezone.utc), None),   # FDX's shape: fine
                                                    ("void", None, None, 101.0),                                                                             # no reason, no time, priced
                                                    ("closed", None, None, None)):                                                                           # closed with no close data
                await s.execute(text("""INSERT INTO alert_picks (id, symbol, picked_direction, leans, entry_price, generated_at, status, algo_version, source, void_reason, voided_at, close_price)
                                        VALUES (gen_random_uuid(), :s, 'bullish', '[]', 100, '2026-09-16 07:00+00', :st, 'v2.0', 'nightly', :r, :at, :cp)"""),
                                {"s": sym, "st": status, "r": reason, "at": at, "cp": close_price})
            await s.commit()
        life, void = await run_checks([check_pick_lifecycle, check_pick_void])
        mine = [row for row in life.rows if row.startswith(sym)]
        assert len(mine) == 1 and "status=closed" in mine[0]                                      # the void picks are not "closed with null close data"
        assert void.level == ERROR and [row for row in void.rows if row.startswith(sym)] == [f"{sym} picked 2026-09-16: no void_reason, no voided_at, close_price set"]
        assert check_pick_void in CHECKS and CHECKS.index(check_pick_void) == CHECKS.index(check_pick_lifecycle) + 1
    finally:
        await _cleanup(sym)


def test_the_digest_counts_voids_and_already_voids_apart():
    labels = ["FDX picked 2026-10-05: already void", "CCL picked 2026-09-21: already void", "NKE picked 2026-09-22: already void"]
    assert "auto-void: 0 voided, 3 already void: FDX picked 2026-10-05: already void; " in digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=labels)[1]
    mixed = labels[:1] + ["XYZ picked 2026-10-01 (open): Report came 9 sessions after entry"]
    assert "auto-void: 1 voided, 1 already void: " in digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=mixed)[1]


@pytest.mark.asyncio
async def test_a_not_comparable_release_figure_is_checked_not_overdue():
    sym = "ZZREL"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("""INSERT INTO release_eps (symbol, report_date, period_end, diluted_eps_gaap, how, evidence, accession, exhibit, filed_on, xbrl_form, xbrl_checked_at, flagged, xbrl_note)
                                    VALUES (:s, '2026-05-01', '2026-04-30', -0.35, 'highlights sentence', 'e', '0000000000-26-000001', 'ex991.htm', '2026-05-01', '10-K', now(), false,
                                            'XBRL holds this quarter only as a derived figure (10-K annual less three quarters, filed 2026-09-10); a release figure is compared only with a quarter XBRL reports directly')"""), {"s": sym})
            await s.commit()
        r = (await run_checks([check_release_eps_checked]))[0]
        assert not any(sym in row for row in r.rows)                                               # never "awaits its XBRL check"
        if r.level == PASS:
            assert "not comparable (XBRL holds the quarter only as a derived figure)" in r.message
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE release_eps SET xbrl_checked_at = NULL, xbrl_note = NULL WHERE symbol = :s"), {"s": sym})
            await s.commit()
        r = (await run_checks([check_release_eps_checked]))[0]
        assert r.level in (WARN, ERROR) and (r.level == ERROR or any(row == f"{sym}: report of 2026-05-01" for row in r.rows))
    finally:
        await _cleanup(sym)

# shares rows other files of this group read across tickers (alert picks, seeded ZZ symbols, index membership): one xdist worker runs them
# (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="shared_rows")
