"""The void standard is automatic: a winner and a loser whose company reported outside the 1-to-5-session entry window are
voided identically; one inside the window is left alone; the step outcome and the digest carry each void."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.notify import digest_message
from app.services.pick_void import ENTRY_MAX_SESSIONS, ENTRY_MIN_SESSIONS, auto_void, sessions_from_entry, standard_reason, void_verdict


def test_sessions_from_entry_and_the_verdict():
    assert sessions_from_entry(date(2026, 10, 5), date(2026, 10, 6)) == 1                      # the next session
    assert sessions_from_entry(date(2026, 10, 5), date(2026, 10, 12)) == 5                     # five sessions out: the edge of the rule
    assert sessions_from_entry(date(2026, 10, 5), date(2026, 10, 28)) == 17
    assert sessions_from_entry(date(2026, 10, 5), date(2026, 10, 5)) == 0 and sessions_from_entry(date(2026, 10, 5), date(2026, 10, 1)) == -2
    n, inside, target = void_verdict(date(2026, 10, 5), date(2026, 10, 19), date(2026, 10, 28))     # FDX
    assert (n, inside, target) == (17, False, date(2026, 10, 12))
    assert sessions_from_entry(date(2026, 9, 21), date(2026, 9, 29)) == 6                           # CCL: Sep 22, 23, 24, 25, 28, 29
    assert void_verdict(date(2026, 9, 21), date(2026, 10, 5), date(2026, 9, 29))[1] is False        # one session outside the rule: the standard voids it
    assert (ENTRY_MIN_SESSIONS, ENTRY_MAX_SESSIONS) == (1, 5)
    assert standard_reason("FedEx", 17, date(2026, 10, 28), date(2026, 10, 12)) == \
        "Report came 17 sessions after entry, the rule allows 1 to 5; FedEx reported Oct 28, 2026, not the targeted Oct 12, 2026"


@pytest.mark.asyncio
async def test_a_winner_and_a_loser_outside_the_window_are_voided_identically_and_one_inside_is_kept():
    sym = "ZZVOID"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Void Test, Inc.', true)"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            # the company reported Sep 30 (a reported EPS); three picks entered Sep 16 (winner, closed), Sep 16 (loser, open) and Sep 25 (inside the window)
            await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, eps_actual, eps_estimate, metadata, created_at, updated_at)
                                    VALUES (gen_random_uuid(), :t, 'earnings', '2026-09-30', 'x', 'finnhub', true, 1.5, 1.4, '{}', now(), now())"""), {"t": tid})
            for day, status, pnl in (("2026-09-16", "closed", 42.0), ("2026-09-16", "open", -30.0), ("2026-09-25", "closed", 10.0)):
                await s.execute(text("""INSERT INTO alert_picks (id, symbol, picked_direction, leans, strategy, entry_price, generated_at, status, algo_version, source,
                                                                 exit_date, expiration, option_pnl_pct, cost_to_enter)
                                        VALUES (gen_random_uuid(), :s, 'bullish', '[]', 'Bull call spread', 100, :g, :st, 'v2.0', 'nightly', :x, '2026-10-30', :p, 5.0)"""),
                                {"s": sym, "g": datetime.fromisoformat(day + "T07:00:00+00:00"), "st": status, "x": date.fromisoformat(day) + timedelta(days=14), "p": pnl})
            await s.commit()
        async with ScriptSessionLocal() as s:
            labels = await auto_void(s, today=date(2026, 10, 6))
            await s.commit()
            rows = (await s.execute(text("SELECT generated_at::date, status, void_reason, voided_at IS NOT NULL, option_pnl_pct FROM alert_picks WHERE symbol = :s ORDER BY generated_at, option_pnl_pct"), {"s": sym})).all()
        voided = [r for r in rows if r[1] == "void"]
        assert len(voided) == 2 and {float(r[4]) for r in voided} == {42.0, -30.0}                 # the winner and the loser, same treatment
        assert len({r[2] for r in voided}) == 1                                                     # identical standard reason
        assert voided[0][2].startswith("Report came 10 sessions after entry, the rule allows 1 to 5; Void Test reported Sep 30, 2026, not the targeted Sep 23, 2026")
        assert all(r[3] for r in voided)
        kept = [r for r in rows if r[0] == date(2026, 9, 25)]
        assert kept and kept[0][1] == "closed" and kept[0][2] is None                               # three sessions out: inside the window
        assert len(labels) == 2 and all(l.startswith(f"{sym} picked 2026-09-16") for l in labels)
        # idempotent: a second pass finds nothing to void
        async with ScriptSessionLocal() as s:
            assert await auto_void(s, today=date(2026, 10, 6)) == []
        title, body = digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=labels)
        assert "auto-voided 2 pick(s)" in body and "Report came 10 sessions after entry" in body
        assert "auto-voided" not in digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=[])[1]
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM alert_picks WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM events WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


def test_the_closer_runs_the_void_standard_and_records_it():
    import inspect
    from app.scripts import close_alert_picks, refresh
    assert "auto_void(session)" in inspect.getsource(close_alert_picks._main) and '"auto_voided": auto_voided' in inspect.getsource(close_alert_picks._main)
    assert 'closer.get("auto_voided")' in inspect.getsource(refresh.digest_fields)
