"""A failing validate names its checks in /health; the FOMC step skips fast and never hangs on one ticker."""
import asyncio
import json
import time
from datetime import date

import pytest

from app.scripts import seed_fomc_reactions as fomc
from app.scripts.validate_data import ERROR, PASS, WARN, OUTCOME_ERROR_CAP, CheckResult, outcome_fields
from app.services.step_outcomes import merged_outcomes


def test_validate_outcome_names_the_failing_checks_and_counts():
    results = [CheckResult("a", PASS, "ok"), CheckResult("b", WARN, "warn"),
               CheckResult("options_read_coverage", ERROR, "Only 0/512 (0.0%) active tickers have an options-read"),
               CheckResult("data_age", ERROR, "1 data feed(s) older than 3 trading days")]
    f = outcome_fields(results)
    assert (f["pass_count"], f["warn_count"], f["error_count"]) == (1, 1, 2)
    assert f["errors"] == [
        {"check": "options_read_coverage", "message": "Only 0/512 (0.0%) active tickers have an options-read"},
        {"check": "data_age", "message": "1 data feed(s) older than 3 trading days"},
    ]
    many = [CheckResult(f"c{i}", ERROR, "x") for i in range(25)]
    assert len(outcome_fields(many)["errors"]) == OUTCOME_ERROR_CAP and outcome_fields(many)["error_count"] == 25


def test_step_fields_merge_with_what_refresh_records():
    before = json.dumps({"Validate data": {"exit": 1, "seconds": 5.6, "at": "t"}, "Other": {"exit": 0}})
    out = merged_outcomes(before, "Validate data", {"error_count": 2, "errors": [{"check": "x", "message": "m"}]})
    assert out["Validate data"] == {"exit": 1, "seconds": 5.6, "at": "t", "error_count": 2, "errors": [{"check": "x", "message": "m"}]}
    assert out["Other"] == {"exit": 0}
    assert merged_outcomes(None, "FOMC reactions", {"nothing_new": True}) == {"FOMC reactions": {"nothing_new": True}}
    assert merged_outcomes("not json", "L", {"k": 1}) == {"L": {"k": 1}}


def test_fomc_skips_fast_only_when_nothing_is_new_and_every_ticker_is_complete():
    assert fomc.nothing_new(date(2026, 9, 17), date(2026, 9, 17), unseeded=0) is True
    assert fomc.nothing_new(date(2026, 9, 17), date(2026, 7, 29), unseeded=0) is False   # a new FOMC date
    assert fomc.nothing_new(date(2026, 9, 17), date(2026, 9, 17), unseeded=3) is False   # tickers missing dates
    assert fomc.nothing_new(date(2026, 9, 17), None, unseeded=0) is False
    assert fomc.nothing_new(None, None, unseeded=0) is True                                # no FOMC dates at all


@pytest.mark.asyncio
async def test_a_stalled_price_fetch_is_skipped_with_a_reason_and_not_retried(monkeypatch):
    monkeypatch.setattr(fomc, "FOMC_FETCH_TIMEOUT", 0.05)
    monkeypatch.setattr(fomc, "BULK_RETRY_DELAYS", (0.5, 0.5, 0.5))
    monkeypatch.setattr(fomc, "_fetch_price_sync", lambda sym: time.sleep(3))
    from app.models.ticker import Ticker
    t0 = time.monotonic()
    ok, ins, upd, nop, reason = await fomc._process_ticker_bulk(Ticker(symbol="HUNG"), [(date(2026, 9, 17), "e")], asyncio.get_running_loop())
    assert ok is False and (ins, upd, nop) == (0, 0, 0)
    assert reason == "price fetch exceeded 0.05s"
    assert time.monotonic() - t0 < 1.0          # no retry ladder for a stall


def test_step_labels_match_refresh():
    from app.scripts.refresh import STEPS
    labels = [l for l, _ in STEPS]
    assert fomc.FOMC_STEP_LABEL in labels
    from app.scripts.validate_data import VALIDATE_STEP_LABEL
    assert VALIDATE_STEP_LABEL in labels
