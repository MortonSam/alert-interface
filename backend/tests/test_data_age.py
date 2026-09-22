"""Validate flags a data feed that stopped updating, counted in trading sessions."""
from datetime import date

from app.scripts.validate_data import PASS, WARN, data_age_result


def test_data_age_uses_trading_days():
    # Monday 2026-09-21: Wednesday 2026-09-16 is 2 sessions back, Tuesday 2026-09-15 is 3, Monday 2026-09-14 is 4
    today = date(2026, 9, 21)
    ok = data_age_result({"analyst actions": date(2026, 9, 15), "options chains": date(2026, 9, 18)}, today)
    assert ok.level == PASS
    stale = data_age_result({"analyst actions": date(2026, 9, 14), "options chains": date(2026, 9, 18), "price bars": None}, today)
    assert stale.level == WARN
    assert any("analyst actions: newest 2026-09-14 (4 sessions ago)" in r for r in stale.rows)
    assert any("price bars: no data at all" in r for r in stale.rows)


def test_data_age_ignores_weekends():
    # Friday 2026-09-18 data seen on Monday 2026-09-21 is 0 sessions old
    assert data_age_result({"x": date(2026, 9, 18)}, date(2026, 9, 21)).level == PASS
