"""Housekeeping from the 2026-10-12 morning check: every nightly step skips inactive tickers, a new validate warning is named in the
digest, the nested repair check judges the database it is given, and a recorded corporate action explains an IV-history price drift."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import refresh
from app.scripts.validate_data import WARN, check_iv_history_price_drift, new_warnings

pytestmark = pytest.mark.xdist_group(name="shared_rows")

SCRIPTS = Path(__file__).resolve().parents[1] / "app" / "scripts"
# steps that read no ticker list of their own: a key check, the index membership itself, macro dates, picks already made, the reads
# warmed through the API's active list, and the validation pass over every stored row
NO_TICKER_LIST = {"ai_key_check": "one API call", "seed_sp500": "it decides which tickers are active", "seed_macro": "FOMC dates, no tickers",
                  "close_alert_picks": "open picks only, whatever their ticker's status", "warm_options_reads": "asks the API for active tickers (active_only=true)",
                  "validate_data": "judges every stored row"}


def test_every_nightly_step_reads_active_tickers_only():
    missing = []
    for label, cmd in refresh.STEPS:
        module = cmd[2].split(".")[-1]
        src = (SCRIPTS / f"{module}.py").read_text()
        if "is_active" in src or module in NO_TICKER_LIST:
            continue
        missing.append(f"{label} ({module})")
    assert missing == [], missing
    # the seven leavers the IV solver skipped as stale on 2026-10-12 (BLDR, CAG, CPB, EPAM, POOL, TAP, TTD) came from the chain keys alone
    assert "parts[1] in active" in (SCRIPTS / "solve_atm_iv.py").read_text()
    assert "SecurityRecord.symbol.in_(active)" in (SCRIPTS / "shadow_price_bars.py").read_text()


def test_new_warnings_are_the_ones_the_previous_night_lacked():
    assert new_warnings(["b", "a", "c"], ["a"]) == ["b", "c"]
    assert new_warnings(["a"], None) == ["a"]
    assert new_warnings([], ["a"]) == []


def test_the_pending_repairs_check_judges_the_session_it_is_given():
    body = (SCRIPTS / "validate_data.py").read_text().split("async def check_pending_repairs")[1].split("\n\n\n")[0]
    assert "r = await fn(session)" in body and "run_checks([fn])" not in body


@pytest.mark.asyncio
async def test_a_recorded_corporate_action_explains_an_iv_price_drift():
    sym, today = "ZZDRF", date.today()
    d0, d1 = today - timedelta(days=3), today - timedelta(days=1)
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Drift Test', true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            for d, px in ((d0, 77.65), (d1, 11.92)):
                await s.execute(text("INSERT INTO iv_history (id, symbol, date, iv_source, current_price, atm_iv) VALUES (gen_random_uuid(), :s, :d, 'courier', :p, 0.4)"), {"s": sym, "d": d, "p": px})
            await s.commit()
            r = await check_iv_history_price_drift(s)
            assert r.level == WARN and any(x.startswith(sym) for x in r.rows), r.rows[:3]          # an unexplained fall warns
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata)
                SELECT gen_random_uuid(), id, 'other', :d, :t, 'edgar', true, '{"corporate_action": "spin_off", "counterparty": "Vylor"}'::jsonb FROM tickers WHERE symbol = :s"""),
                            {"d": today - timedelta(days=2), "t": f"{sym} spin off: Vylor", "s": sym})
            await s.commit()
            r = await check_iv_history_price_drift(s)
            assert not any(x.startswith(sym) for x in r.rows), r.rows[:3]                           # the spin-off between the rows explains it
        finally:
            await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM iv_history WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


# ── the run's timing record and the chains step's start (2026-10-12) ──

def test_each_step_records_its_start_duration_and_end_and_the_history_keeps_thirty_runs():
    from datetime import datetime, timezone
    import json
    t = datetime(2026, 10, 12, 7, 37, 31, tzinfo=timezone.utc)
    assert refresh.step_timing(t, 606.4, True) == {"started_at": "2026-10-12T07:37:31+00:00", "seconds": 606.4, "finished_at": "2026-10-12T07:47:37.400000+00:00", "ok": True}
    runs = [{"slot": f"2026-09-{d:02d}", "steps": {}} for d in range(1, 31)]
    out = refresh.timings_history(json.dumps(runs), {"slot": "2026-10-12", "steps": {"Validate data": {"seconds": 22.9}}})
    assert len(out) == 30 and out[-1]["slot"] == "2026-10-12" and out[0]["slot"] == "2026-09-02"
    assert [r["slot"] for r in refresh.timings_history(json.dumps(out), {"slot": "2026-10-12", "steps": {}})].count("2026-10-12") == 1   # a resumed run replaces its slot
    assert refresh.timings_history("not json", {"slot": "x"}) == [{"slot": "x"}]
    assert refresh.TIMINGS_KEY == "nightly_timings"


def test_the_chains_step_warns_when_it_starts_more_than_45_minutes_after_its_schedule():
    from app.scripts.validate_data import CHAINS_START_SLACK_MINUTES, CHECKS, chains_start_delay_minutes, check_chains_step_start
    assert check_chains_step_start in CHECKS and CHAINS_START_SLACK_MINUTES == 45
    assert chains_start_delay_minutes("2026-10-12T07:37:31+00:00") == 32.5          # 03:37:31 EDT on 2026-10-12
    assert chains_start_delay_minutes("2026-10-12T03:37:31-04:00") == 32.5          # the step's own started_local
    assert chains_start_delay_minutes("2026-10-12T08:00:00+00:00") == 55.0 > CHAINS_START_SLACK_MINUTES
    assert chains_start_delay_minutes("2026-12-10T08:05:00+00:00") == 0.0            # EST: 03:05 New York is 08:05 UTC
    assert chains_start_delay_minutes(None) is None and chains_start_delay_minutes("garbage") is None
