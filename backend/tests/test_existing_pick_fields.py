"""The duplicate-pick response carries the stored pick's own date and direction, never the request time."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers.thesis import existing_pick_fields


def test_fields_come_from_the_stored_pick():
    stored = SimpleNamespace(
        generated_at=datetime(2026, 9, 20, 6, 14, tzinfo=timezone.utc), picked_direction="bullish",
        leans=[{"signal": "earnings", "direction": "bullish", "justification": "x"}],
    )
    f = existing_pick_fields(stored)
    assert f["existing_pick"] is True
    assert f["generated_at"] == "2026-09-20T06:14:00+00:00"
    assert f["existing_since"] == "2026-09-20"
    assert f["picked_direction"] == "bullish"
    assert f["leans"][0].signal == "earnings"
    assert not f["generated_at"].startswith(datetime.now(timezone.utc).date().isoformat())


def test_both_duplicate_branches_use_the_helper():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
    assert src.count("**existing_pick_fields(existing)") == 1 and src.count("fields = existing_pick_fields(existing)") == 1
    assert '"generated_at": existing.generated_at' not in src.replace("def existing_pick_fields", "")[src.index("async def compute_alert_pick"):]
