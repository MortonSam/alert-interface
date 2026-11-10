"""Sam, 2026-11-10: a credit failure pauses the night's AI cleanly, with one alert and then reminders; under a small cap visitors keep
half of it; until SAVER_UNTIL notes go to the most recent reporters, largest first, with no 8-K rewrites or rechecks."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.scripts import generate_notes as G
from app.services import ai_pause as P
from app.services import ai_spend as A

pytestmark = pytest.mark.xdist_group(name="ai_spend_days")


def test_the_pause_alerts_once_the_first_night_then_reminds_each_night():
    p = P.started(None, "billing", datetime(2026, 11, 5, 7, 32, tzinfo=timezone.utc))
    assert P.started(p, "billing", datetime(2026, 11, 6, tzinfo=timezone.utc)) is p                 # a pause keeps its start
    title, body, high = P.alert_for(p, date(2026, 11, 5), ["Research notes (nightly)"])
    assert high and "AI paused" in title and "Research notes (nightly)" in body and "nothing is marked failed" in body
    assert P.alert_for({**p, "alerted_on": "2026-11-05"}, date(2026, 11, 5), []) is None            # one a night
    title, body, high = P.alert_for({**p, "alerted_on": "2026-11-05"}, date(2026, 11, 7), ["Research notes (nightly)"])
    assert not high and title.startswith("Reminder") and "Night 3" in body
    assert "AI paused since Nov 5 (night 3, billing)" in P.digest_line(p, date(2026, 11, 7), ["Research note check"])
    assert P.digest_line(None, date(2026, 11, 7), []) == "" and P.parse("") is None and P.parse("{}") is None


def test_a_small_cap_leaves_visitors_half_and_notes_one_at_a_time():
    assert A.visitor_reserve(15.0) == 4.0 and A.visitor_reserve(3.0) == 1.5
    assert A.notes_night_budget(3.0, False) == 1.5 and A.nightly_room(3.0, 0.4) == pytest.approx(1.1)
    assert G.concurrency_for(1.5) == 1 and G.concurrency_for(6.0) == 4


def test_until_the_credit_notes_go_to_the_latest_reporters_largest_first_with_no_rechecks():
    from app.services.note_claims import NOTE_CHECK_VERSION
    rows = [("OLDBIG", "complete", True, NOTE_CHECK_VERSION, 900, False, False, date(2026, 11, 2)),
            ("NEWSMALL", "complete", True, NOTE_CHECK_VERSION, 10, False, False, date(2026, 11, 9)),
            ("NEWBIG", "failed", False, None, 800, False, False, date(2026, 11, 9)),
            ("RECHECK", "complete", False, 1, 999, False, False, date(2026, 11, 9))]
    assert G.queue(rows, 10, saver=True) == ["NEWBIG", "NEWSMALL", "OLDBIG"]
    assert G.queue(rows, 10) == ["NEWBIG", "RECHECK", "OLDBIG", "NEWSMALL"]
    assert A.saver_on(date(2026, 11, 18)) and not A.saver_on(date(2026, 11, 19))


@pytest.mark.asyncio
async def test_a_paused_night_sends_no_model_call(monkeypatch):
    from app.database import ScriptSessionLocal
    async with ScriptSessionLocal() as s:
        await s.execute(text("""INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"""), {"k": P.PAUSE_KEY, "v": '{"since": "2026-11-05T07:32:00+00:00", "kind": "billing"}'})
        await s.commit()
        try:
            with pytest.raises(A.NightlyBudgetReached, match="AI paused since Nov 5"):
                await A.check_nightly(s, "claude-haiku-4-5-20251001", {"messages": [], "max_tokens": 5})
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": P.PAUSE_KEY})
            await s.commit()


def test_until_the_plan_credit_the_cap_is_held_to_three_dollars(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ai_daily_spend_cap_usd", 15.0)
    assert A.cap_usd(date(2026, 11, 10)) == 3.0 and A.cap_usd(date(2026, 11, 19)) == 15.0
    monkeypatch.setattr(settings, "ai_daily_spend_cap_usd", 2.0)
    assert A.cap_usd(date(2026, 11, 10)) == 2.0                        # a lower cap set on Railway still wins
