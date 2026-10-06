"""Automation block A: IV dated by its chain, per-dataset ages behind /health, ntfy messages, the courier as a stored fact,
fail-closed gates, and the home page without unsourced figures."""
import inspect
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import chain_courier, refresh, seed_macro, snapshot_iv, warm_options_reads
from app.scripts.validate_data import CHECKS, ERROR, PASS, WARN, CheckResult, check_alerting_configured, check_chain_coverage, outcome_fields, run_checks
from app.services import notify
from app.services.dataset_freshness import COURIER_STEP_LABEL, DATASETS, courier_run_fields, courier_summary, dataset_ages, run_status

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)


# ── 1. IV rows dated by the chain ─────────────────────────────────────────────

def test_a_stale_chain_is_refused_with_its_age_in_sessions_and_a_fresh_one_passes():
    today = date(2026, 10, 6)                                                    # a Tuesday
    assert snapshot_iv.stale_chain_reason("2026-10-05", today) is None           # one session old
    assert snapshot_iv.stale_chain_reason("2026-10-02", today) is None           # two sessions: the freshness rule's limit
    assert snapshot_iv.stale_chain_reason("2026-10-01", today) == "options chain is 3 sessions old"
    assert snapshot_iv.stale_chain_reason("2026-09-24", today) == "options chain is 8 sessions old"
    assert snapshot_iv.stale_chain_reason(None, today) == "options chain has no date"
    src = inspect.getsource(snapshot_iv._snapshot_one)
    assert '"date": row_date' in src and "row_date = date.fromisoformat(chain_date)" in src and '"date": today' not in src
    solver = inspect.getsource(__import__("app.scripts.solve_atm_iv", fromlist=["run"]).run)
    assert "chain_store.is_fresh(d.isoformat())" in solver and "skipped_stale" in solver


@pytest.mark.asyncio
async def test_the_iv_store_names_the_chain_age_when_the_window_is_empty():
    from app.services import chain_store
    from app.services.iv_store import get_servable_iv, stale_chain_line
    sym = "ZZIVC"
    try:
        async with ScriptSessionLocal() as s:
            await chain_store.put_chain(s, sym, "2026-10-16", {"calls": [], "puts": [], "expiration": "2026-10-16", "chain_last_trade": "2026-09-24",
                                                                  "underlying_price": 10.0, "chain_source": "courier"}, chain_store.COURIER)
            await s.commit()
        async with ScriptSessionLocal() as s:
            line = await stale_chain_line(s, sym, date(2026, 10, 6))
            state = await get_servable_iv(s, sym, date(2026, 10, 6))
        assert line == "options chain is 8 sessions old"
        assert state.value is None and "options chain is 8 sessions old" in state.reason
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("delete from system_metadata where key = :k"), {"k": chain_store.chain_key(sym, "2026-10-16")})
            await s.commit()


# ── 2. per-dataset ages and the run's status ─────────────────────────────────

def test_dataset_ages_take_the_oldest_success_and_name_failed_steps():
    outcomes = {"Historical reactions (--all)": {"exit": 0}, "Missed reports (catch_up_reports)": {"exit": 1}, "IV + RV snapshot (snapshot_iv)": {"exit": 0}}
    stamps = {"Historical reactions (--all)": "2026-10-06T06:40:00+00:00", "Missed reports (catch_up_reports)": "2026-10-05T06:45:00+00:00",
              "IV + RV snapshot (snapshot_iv)": "2026-10-06T07:10:00+00:00"}
    ages = dataset_ages(outcomes, stamps)
    assert ages["reactions"]["at"] == "2026-10-05T06:45:00+00:00" and ages["reactions"]["ok"] is False and ages["reactions"]["failed"] == ["Missed reports (catch_up_reports)"]
    assert ages["iv"] == {"at": "2026-10-06T07:10:00+00:00", "ok": True, "failed": [], "steps": ["IV + RV snapshot (snapshot_iv)"]}
    assert ages["chains"]["at"] is None and ages["chains"]["ok"] is False          # the courier has never recorded a run
    assert set(DATASETS) == {"prices", "chains", "reactions", "analyst", "iv", "rv", "earnings_calendar"}
    labels = {label for label, _ in refresh.STEPS}
    for steps in DATASETS.values():
        for step in steps:
            assert step in labels or step == COURIER_STEP_LABEL, step


def test_run_status_is_degraded_with_the_failed_step_names():
    labels = [label for label, _ in refresh.STEPS]
    assert run_status({"Validate data": {"exit": 0}}, labels) == ("ok", [])
    assert run_status({"ATM IV (solver)": {"exit": -1}, "Validate data": {"exit": 1}, "Old step": {"exit": 1}}, labels) == ("degraded", ["ATM IV (solver)", "Validate data"])


def test_last_refreshed_at_needs_every_data_step_clean_and_validate_is_a_judge_not_a_data_step():
    assert refresh.should_record_refresh([("Ticker data (seed_sp500)", True), ("Validate data", False)])
    assert not refresh.should_record_refresh([("Ticker data (seed_sp500)", True), ("ATM IV (solver)", False), ("Validate data", True)])
    src = inspect.getsource(refresh.main)
    assert "if should_record_refresh(results):" in src and "digest_fields(" in src


@pytest.mark.asyncio
async def test_health_reports_degraded_and_the_failed_step_when_a_step_outcome_failed():
    from app.main import health_check
    from app.services.step_outcomes import record_step_fields
    label = "ATM IV (solver)"
    async with ScriptSessionLocal() as s:
        raw = (await s.execute(text("select value from system_metadata where key = 'step_outcomes'"))).scalar()
    before = (json.loads(raw) if raw else {}).get(label, {})
    try:
        await record_step_fields(label, {"exit": -1, "seconds": 600.1, "at": NOW.isoformat()})
        h = await health_check()
        body = h if isinstance(h, dict) else json.loads(h.body)
        assert body["status"] == "degraded" and label in body["failed_steps"]
        assert "datasets" in body and set(body["datasets"]) == set(DATASETS)
        assert body["datasets"]["reactions"].keys() == {"at", "ok", "failed", "steps"}
    finally:
        await record_step_fields(label, {**before, "exit": before.get("exit", 0)} if before else {"exit": 0})


# ── 3. alerting ───────────────────────────────────────────────────────────────

def test_ntfy_is_a_noop_without_a_topic_and_validate_warns_about_it(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "")
    assert notify.notify_sync("t", "m") is False and notify.configured() is False
    assert check_alerting_configured in CHECKS


@pytest.mark.asyncio
async def test_alerting_check_level_follows_the_topic(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "")
    assert (await run_checks([check_alerting_configured]))[0].level == WARN
    monkeypatch.setattr(notify.settings, "ntfy_topic", "alert-interface-test")
    assert (await run_checks([check_alerting_configured]))[0].level == PASS


def test_the_message_formats():
    assert notify.step_failure_message("ATM IV (solver)", -1, 600.1, "KeyError: x") == ("Nightly step failed: ATM IV (solver)", "timed out after 600s\nKeyError: x")
    assert notify.step_failure_message("Auto-pick", 1, 12.4, None) == ("Nightly step failed: Auto-pick", "exit 1 after 12s")
    assert notify.validate_error_message("chain_coverage", "40/511 (8%) active tickers have a fresh chain (below 90%): the courier did not deliver", ["AAPL  no fresh chain", "MSFT  no fresh chain", "a", "b"]) == (
        "Validate ERROR: chain_coverage", "40/511 (8%) active tickers have a fresh chain (below 90%): the courier did not deliver\n· AAPL  no fresh chain\n· MSFT  no fresh chain\n· a")
    title, body = notify.digest_message("2026-10-06", 26, 27, ["ATM IV (solver)"], {"error_count": 2, "warn_count": 13}, 97.5,
                                        {"ran": True, "at_local": "16:07 ET", "tickers": 421, "failures": 91})
    assert title == "Nightly 2026-10-06: 26/27 steps passed"
    assert body == "failed: ATM IV (solver) | validate: 2 errors, 13 warnings | chain coverage 98% | courier ran 16:07 ET, 421 tickers (91 failed)"
    _, body = notify.digest_message("2026-10-06", 27, 27, [], None, None, {"ran": False})
    assert body == "all steps passed | chain coverage unknown | courier did not run"


def test_sent_messages_carry_title_priority_and_tags(monkeypatch):
    calls = []
    class R:
        def raise_for_status(self): pass
    monkeypatch.setattr(notify.settings, "ntfy_topic", "alert-interface-test")
    monkeypatch.setattr(notify.settings, "ntfy_server", "https://ntfy.example")
    monkeypatch.setattr(notify.httpx, "post", lambda url, content, headers, timeout: calls.append((url, content, headers)) or R())
    assert notify.notify_sync("Nightly step failed: X", "exit 1 after 3s", notify.PRIORITY_HIGH, ("warning",)) is True
    assert calls == [("https://ntfy.example/alert-interface-test", b"exit 1 after 3s", {"Title": "Nightly step failed: X", "Priority": "high", "Tags": "warning"})]


def test_courier_runs_accumulate_within_a_run_and_the_digest_knows_whether_it_ran():
    first = courier_run_fields(None, NOW, 5, 18, [], "2026-10-05T16:06:12-04:00")
    assert first["tickers"] == 5 and first["chains"] == 18 and first["exit"] == 0 and first["run_started_at"] == NOW.isoformat()
    second = courier_run_fields(first, NOW + timedelta(minutes=20), 7, 25, ["X: HTTP 502"], None)
    assert (second["tickers"], second["chains"], second["failures"], second["exit"]) == (12, 43, 1, 1)
    assert second["run_started_at"] == NOW.isoformat() and second["captured_at"] == "2026-10-05T16:06:12-04:00"
    fresh = courier_run_fields(second, NOW + timedelta(hours=23), 3, 9, [], "2026-10-06T16:05:40-04:00")
    assert fresh["tickers"] == 3 and fresh["run_started_at"] == (NOW + timedelta(hours=23)).isoformat()
    ran = courier_summary({COURIER_STEP_LABEL: {"at": (NOW - timedelta(hours=16)).isoformat(), "tickers": 421, "failures": 91}}, NOW)
    assert ran["ran"] is True and ran["at_local"] == "12:00 ET" and ran["tickers"] == 421
    assert courier_summary({COURIER_STEP_LABEL: {"at": (NOW - timedelta(hours=40)).isoformat()}}, NOW)["ran"] is False
    assert courier_summary({}, NOW)["ran"] is False
    assert "_record_courier_run(db" in inspect.getsource(__import__("app.routers.admin", fromlist=["ingest_options_chains"]).ingest_options_chains)


# ── 4. courier guards ─────────────────────────────────────────────────────────

def test_chain_coverage_below_the_floor_is_an_error_and_carries_its_figure():
    src = inspect.getsource(check_chain_coverage)
    assert '"chain_coverage", ERROR' in src and '"chain_coverage", WARN' not in src and "CHAIN_COVERAGE_MIN_PCT" in src
    fields = outcome_fields([CheckResult("chain_coverage", PASS, "ok", figures={"chain_coverage_pct": 97.5}), CheckResult("x", ERROR, "bad")])
    assert fields["figures"] == {"chain_coverage_pct": 97.5} and fields["error_count"] == 1


def test_the_courier_has_no_fallback_list_and_stops_without_the_ticker_list():
    src = inspect.getsource(chain_courier)
    assert "FALLBACK_TICKERS" not in src and "class TickerListUnavailable" in src
    assert 'print(f"ERROR: {redact(exc)}. Nothing pushed.", file=sys.stderr)' in src and "return 1" in inspect.getsource(chain_courier.main)


# ── 5. fail-closed gates ──────────────────────────────────────────────────────

def test_generation_routes_warm_and_fred_fail_closed():
    tickers_src = open(__import__("app.routers.tickers", fromlist=["router"]).__file__).read()
    assert tickers_src.count("if not settings.admin_token or token != settings.admin_token:") == 2
    assert "if settings.admin_token and token != settings.admin_token:" not in tickers_src
    assert "return 1  # fail closed" in inspect.getsource(warm_options_reads.main)
    macro = inspect.getsource(seed_macro)
    assert "fetch_bls_via_web" not in macro and "FRED_API_KEY is not set" in macro and "sys.exit(asyncio.run(main()))" in macro
