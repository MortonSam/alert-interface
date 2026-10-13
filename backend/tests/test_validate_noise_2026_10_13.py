"""2026-10-13: the reaction-equality checks warn only on rows the stored daily bars do not confirm, and the nightly digest says when
there is no previous warning list to compare, names the new warnings or says none are new, and names the ones that cleared."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.enums import EventType
from app.scripts.validate_data import _bars_unconfirmed, cleared_warnings, new_warnings
from app.services.notify import digest_message, warnings_tail

pytestmark = pytest.mark.xdist_group(name="shared_rows")

SCRIPTS = Path(__file__).resolve().parents[1] / "app" / "scripts"


SYM = "ZZEQ"
# amc earnings on Wed 2025-11-05: base close(T), 1d close(T+1), 3d close(T+3), 5d close(T+5); T+3 and T+5 close at 110, so 3d = 5d = +10%
CLOSES = {"2025-11-04": 99.0, "2025-11-05": 100.0, "2025-11-06": 105.0, "2025-11-07": 103.0, "2025-11-10": 110.0, "2025-11-11": 108.0,
          "2025-11-12": 110.0, "2025-11-13": 111.0, "2025-11-14": 112.0}


@pytest.mark.asyncio
async def test_an_equal_pair_warns_only_when_the_stored_bars_do_not_confirm_it():
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": SYM})
        for d, c in CLOSES.items():
            await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, open, high, low, close, volume, factor, split_ratio, dividend, fetched_at)
                                    VALUES (:s, :d, 'sec_zzeq', :c, :c, :c, :c, 1000000, 1.0, 1.0, 0, :t)"""),
                            {"s": SYM, "d": date.fromisoformat(d), "c": c, "t": datetime.now(timezone.utc)})
        await s.commit()
    try:
        real = SimpleNamespace(symbol=SYM, event_date=date(2025, 11, 5), event_type=EventType.EARNINGS, report_timing="amc",
                               pct_change_3d=Decimal("10.0000"), pct_change_5d=Decimal("10.0000"))
        stale = SimpleNamespace(symbol=SYM, event_date=date(2025, 11, 5), event_type=EventType.EARNINGS, report_timing="amc",
                                pct_change_3d=Decimal("5.0000"), pct_change_5d=Decimal("5.0000"))
        unknown = SimpleNamespace(symbol=SYM, event_date=date(2025, 11, 5), event_type=EventType.EARNINGS, report_timing="unknown",
                                  pct_change_3d=Decimal("10.0000"), pct_change_5d=Decimal("10.0000"))
        async with ScriptSessionLocal() as s:
            out = await _bars_unconfirmed(s, [real, stale, unknown], "pct_change_3d", "pct_change_5d")
        assert out == [stale, unknown]          # the coincidence the bars show is confirmed; a stale pair and an unrecomputable row warn
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": SYM})
            await s.commit()


def test_the_digest_says_when_there_is_no_list_to_compare_and_names_what_cleared():
    assert new_warnings(["a", "b"], None) is None and cleared_warnings(["a"], None) is None
    assert new_warnings(["a", "b"], ["a", "c"]) == ["b"] and cleared_warnings(["a", "b"], ["a", "c"]) == ["c"]
    assert warnings_tail({"new_warnings": None}) == "(no previous list to compare)"
    assert warnings_tail({"new_warnings": [], "cleared_warnings": []}) == "(none new)"
    assert warnings_tail({"new_warnings": ["b"], "cleared_warnings": ["c", "d"]}) == "(new: b), cleared: c, d"
    body = digest_message("2026-10-14", 37, 37, [], {"error_count": 0, "warn_count": 18, "new_warnings": None}, 90.0, None)[1]
    assert "validate: 0 errors, 18 warnings (no previous list to compare)" in body
    body = digest_message("2026-10-14", 37, 37, [], {"error_count": 0, "warn_count": 17, "new_warnings": [], "cleared_warnings": ["courier_delivered"]}, 90.0, None)[1]
    assert "validate: 0 errors, 17 warnings (none new), cleared: courier_delivered" in body
    main = (SCRIPTS / "validate_data.py").read_text().split("async def main() -> int:")[1].split("\n\n\n")[0]
    assert 'fields["warn_names_at"]' in main and 'fields["warn_baseline_at"]' in main     # each list is stored with when it was stored
