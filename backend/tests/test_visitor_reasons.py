"""Reasons shown on the page are plain language; technical detail stays in logs."""
from datetime import date
from types import SimpleNamespace

from app.services.price_freshness import assess_history
from app.services.rv_store import _STATUS_REASONS, _why_not

DEV_TOKENS = ("status", "snapshot", "sample", "sessions", "'", "_", "None", "%")


def _plain(text: str) -> bool:
    return bool(text) and not any(tok in text for tok in DEV_TOKENS)


def test_rv_status_reasons_are_plain():
    for status in ("no_data", "insufficient", "fetch_failed", "data_error", "something_new"):
        row = SimpleNamespace(status=status, as_of_date=date(2026, 9, 21), sample_days=0, last_bar_date=None)
        reason, detail = _why_not(row, cutoff=date(2026, 9, 14))
        assert _plain(reason), reason
        assert status in detail                      # the technical detail is kept, for the log
    assert _STATUS_REASONS["no_data"] == "Not enough recent price history to compute realized volatility"


def test_rv_old_snapshot_and_stale_history_reasons_are_plain():
    old = SimpleNamespace(status="ok", as_of_date=date(2026, 8, 1), sample_days=252, last_bar_date=None)
    assert _plain(_why_not(old, cutoff=date(2026, 9, 14))[0])
    stale = SimpleNamespace(status="ok", as_of_date=date(2026, 9, 21), sample_days=252, last_bar_date=date(2026, 8, 21))
    reason, detail = _why_not(stale, cutoff=date(2026, 9, 14))
    assert _plain(reason) and "2026-08-21" in reason
    assert "sessions" in detail
    ok = SimpleNamespace(status="ok", as_of_date=date(2026, 9, 21), sample_days=252, last_bar_date=date(2026, 9, 18))
    assert _why_not(ok, cutoff=date(2026, 9, 14)) is None


def test_history_reasons_are_plain_and_carry_detail_separately():
    today = date(2026, 9, 21)
    stale = assess_history(date(2026, 8, 21), 63.66, 65.35, today=today)
    mismatch = assess_history(date(2026, 9, 18), 68.14, 184.06, today=today)
    none = assess_history(None, None, None, today=today)
    for state in (stale, mismatch, none):
        assert _plain(state.reason), state.reason
    assert "63%" in mismatch.detail and "sessions" in stale.detail
