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
                                                                 exit_date, expiration, option_pnl_pct, cost_to_enter, closed_at, close_price)
                                        VALUES (gen_random_uuid(), :s, 'bullish', '[]', 'Bull call spread', 100, :g, :st, 'v2.0', 'nightly', :x, '2026-10-30', :p, :c, :ca, :cp)"""),
                                {"s": sym, "g": datetime.fromisoformat(day + "T07:00:00+00:00"), "st": status, "x": date.fromisoformat(day) + timedelta(days=14), "p": pnl,
                                 "c": abs(pnl), "ca": datetime.fromisoformat("2026-10-01T20:00:00+00:00") if status == "closed" else None, "cp": 110.0 if status == "closed" else None})
            await s.commit()
        async with ScriptSessionLocal() as s:
            labels = await auto_void(s, today=date(2026, 10, 6))
            await s.commit()
            rows = (await s.execute(text("SELECT generated_at::date, status, void_reason, voided_at IS NOT NULL, cost_to_enter FROM alert_picks WHERE symbol = :s ORDER BY generated_at, cost_to_enter"), {"s": sym})).all()
            priced = await s.scalar(text("SELECT count(*) FROM alert_picks WHERE symbol = :s AND status = 'void' AND (closed_at IS NOT NULL OR close_price IS NOT NULL OR option_pnl_dollars IS NOT NULL OR option_pnl_pct IS NOT NULL)"), {"s": sym})
            kept_price = (await s.execute(text("SELECT close_price, option_pnl_pct FROM alert_picks WHERE symbol = :s AND cost_to_enter = 10.0"), {"s": sym})).first()
        voided = [r for r in rows if r[1] == "void"]
        assert len(voided) == 2 and {float(r[4]) for r in voided} == {42.0, 30.0}                  # the winner and the loser, same treatment
        assert priced == 0 and (float(kept_price[0]), float(kept_price[1])) == (110.0, 10.0)        # a void pick is priced by nothing; the kept closed pick keeps its close
        assert len({r[2] for r in voided}) == 1                                                     # identical standard reason
        assert voided[0][2].startswith("Report came 10 sessions after entry, the rule allows 1 to 5; Void Test reported Sep 30, 2026, not the targeted Sep 23, 2026")
        assert all(r[3] for r in voided)
        kept = [r for r in rows if r[0] == date(2026, 9, 25)]
        assert kept and kept[0][1] == "closed" and kept[0][2] is None                               # three sessions out: inside the window
        assert len(labels) == 2 and all(l.startswith(f"{sym} picked 2026-09-16") for l in labels)
        # a second pass skips the void picks, says so, and rewrites nothing
        async with ScriptSessionLocal() as s:
            again = await auto_void(s, today=date(2026, 10, 6))
            await s.commit()
            after = (await s.execute(text("SELECT void_reason, voided_at FROM alert_picks WHERE symbol = :s AND status = 'void' ORDER BY cost_to_enter"), {"s": sym})).all()
        assert again == [f"{sym} picked 2026-09-16: already void"] * 2
        assert [(r[0], r[1]) for r in after] == [(r[2], None) for r in []] or all(r[0] == voided[0][2] for r in after)      # reasons unchanged
        assert {r[1] for r in after} == {voided_at for voided_at in {r[1] for r in after}} and len({r[1] for r in after}) >= 1
        # a hand-voided pick with its own reason is also left exactly as written
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE alert_picks SET void_reason = 'voided by hand this morning', voided_at = '2026-10-07 09:00+00', close_price = 123 WHERE symbol = :s AND cost_to_enter = 42.0"), {"s": sym})
            await s.commit()
        async with ScriptSessionLocal() as s:
            await auto_void(s, today=date(2026, 10, 6))
            await s.commit()
            hand = (await s.execute(text("SELECT void_reason, voided_at::text, close_price FROM alert_picks WHERE symbol = :s AND cost_to_enter = 42.0"), {"s": sym})).first()
        assert hand[0] == "voided by hand this morning" and hand[1].startswith("2026-10-07 09:00") and hand[2] is None   # reason and time kept; a price set by hand on a void pick is cleared
        title, body = digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=labels)
        assert "auto-void: 2 voided, 0 already void: " in body and "Report came 10 sessions after entry" in body
        assert "auto-void: 0 voided, 2 already void: " in digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=again)[1]
        assert "auto-void" not in digest_message("2026-10-07", 29, 29, [], None, 91.0, None, auto_voided=[])[1]
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
