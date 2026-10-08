"""Automation block C: delisting and index membership as rules, renames in place with aliases, idempotent nightly recompute
and reclassification, and the nightly on the New York clock with per-step resume."""
import inspect
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import build_security_records as bsr
from app.scripts import recompute_reactions_intrinio as rr
from app.scripts import refresh, seed_sp500
from app.scripts.validate_data import CHECKS, ERROR, PASS, WARN, check_delisting_signals, check_pending_repairs, check_symbol_matches_record, run_checks
from app.services import cadence as cad
from app.services import nightly_clock as nc
from app.services import ticker_aliases
from app.services.ticker_rename import absorb_duplicate, canonical_symbol, detect_rename, rename_symbol, symbol_tables, unique_keys
from app.services.trading_calendar import CALENDAR_CORRECTIONS

NY = ZoneInfo("America/New_York")


# ── 1. delisting and membership rules ────────────────────────────────────────

def test_the_three_delisting_signals_and_what_each_means():
    today = date(2026, 10, 6)
    assert bsr.delisting_signals(date(2026, 8, 14), False, False, today) == ["no Intrinio price since 2026-08-14", "Intrinio marks the record inactive", "absent from the constituent list"]
    assert bsr.delisting_signals(date(2026, 10, 5), True, False, today) == ["absent from the constituent list"]      # the index leavers: one signal
    assert bsr.delisting_signals(date(2026, 10, 2), True, True, today) == []                                        # 10-02 to 10-06: two sessions, not stale
    assert bsr.delisting_signals(date(2026, 10, 1), True, True, today) == ["no Intrinio price since 2026-10-01"]
    assert bsr.delisting_signals(None, None, True, today) == []
    assert not hasattr(__import__("app.services.security_records", fromlist=["x"]), "DELISTED")


@pytest.mark.asyncio
async def test_all_three_signals_delist_two_do_not_and_validate_errors_on_two():
    sym = "ZZDL3"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, index_member) VALUES (gen_random_uuid(), :s, 'Delist rule test', true, false)"), {"s": sym})
            await s.execute(text("""INSERT INTO security_records (symbol, intrinio_security_id, valid_from, role, source, last_price_date, intrinio_active, intrinio_ticker)
                                    VALUES (:s, 'sec_zz', '2020-01-02', 'current', 'intrinio', '2026-08-14', true, :t)"""), {"s": sym, "t": sym})
            await s.commit()
        r = (await run_checks([check_delisting_signals]))[0]
        assert r.level == ERROR and any(x.startswith(f"{sym}: no Intrinio price since 2026-08-14; absent") for x in r.rows)
        async with ScriptSessionLocal() as s:
            flipped = await bsr.apply_delisting_rule(s, date(2026, 10, 6))
            await s.commit()
        assert sym not in flipped                                    # two signals: left active, reported by validate
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE security_records SET intrinio_active = false WHERE symbol = :s"), {"s": sym})
            await s.commit()
        async with ScriptSessionLocal() as s:
            flipped = await bsr.apply_delisting_rule(s, date(2026, 10, 6))
            await s.commit()
            row = (await s.execute(text("SELECT is_active, inactive_reason, inactive_since FROM tickers WHERE symbol = :s"), {"s": sym})).one()
            closed = (await s.execute(text("SELECT valid_to FROM security_records WHERE symbol = :s"), {"s": sym})).scalar()
        assert flipped[sym]["date"] == "2026-08-14" and row.is_active is False and row.inactive_since == date(2026, 8, 14)
        assert row.inactive_reason.startswith("delisted: last session 2026-08-14") and closed == date(2026, 8, 14)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


@pytest.mark.asyncio
async def test_index_leavers_become_inactive_with_the_date_and_a_short_scrape_changes_nothing():
    syms = ["ZZIL1", "ZZIL2"]
    try:
        async with ScriptSessionLocal() as s:
            for sym in syms:
                await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, index_member) VALUES (gen_random_uuid(), :s, 'Leaver test', true, true)"), {"s": sym})
            await s.commit()
        async with ScriptSessionLocal() as s:
            assert await seed_sp500.deactivate_index_leavers(s, ["AAPL"] * 10, date(2026, 10, 6)) == {}      # a broken scrape
            active = (await s.execute(text("SELECT symbol FROM tickers WHERE is_active AND symbol <> 'ZZIL2'"))).scalars().all()
            out = await seed_sp500.deactivate_index_leavers(s, list(active), date(2026, 10, 6))
            await s.commit()
            rows = dict((await s.execute(text("SELECT symbol, inactive_reason FROM tickers WHERE symbol = ANY(:s) AND NOT is_active"), {"s": syms})).all())
        assert list(out) == ["ZZIL2"] and rows == {"ZZIL2": "left the S&P 500 (first missing from the constituent list on 2026-10-06)"}
        assert seed_sp500.MIN_CONSTITUENTS == 480
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM tickers WHERE symbol = ANY(:s)"), {"s": syms})
            await s.commit()


def test_a_rename_is_the_same_record_under_a_new_ticker_nobody_uses():
    body = {"id": "sec_gkDL4Q", "ticker": "VMRK"}
    assert detect_rename("EQR", "sec_gkDL4Q", body, {"AAPL"}) == "VMRK"
    assert detect_rename("EQR", "sec_other", body, {"AAPL"}) is None            # a different security took the ticker: not a rename
    assert detect_rename("EQR", "sec_gkDL4Q", body, {"VMRK"}) is None           # the new symbol exists for we know not what
    assert detect_rename("EQR", "sec_gkDL4Q", body, {"VMRK"}, {"VMRK": "sec_other"}) is None     # another security owns it
    assert detect_rename("EQR", "sec_gkDL4Q", body, {"VMRK"}, {"VMRK": "sec_gkDL4Q"}) == "VMRK"  # a duplicate row of the same security
    assert detect_rename("EQR", "sec_gkDL4Q", {"id": "sec_gkDL4Q", "ticker": "EQR"}, set()) is None
    assert detect_rename("EQR", None, body, set()) is None
    assert detect_rename("BRK-B", "sec_9Xa0Lg", {"id": "sec_9Xa0Lg", "ticker": "BRK.B"}, set()) is None   # a dot is not a rename
    assert canonical_symbol("bf.b") == "BF-B"


@pytest.mark.asyncio
async def test_the_alias_cache_loads_on_first_call_whatever_the_clock_reads_and_again_after_the_window():
    """time.monotonic() counts from boot; a process younger than CACHE_SECONDS must still load the table on its first call and after a reset."""
    class FakeSession:
        def __init__(self): self.reads = 0
        async def execute(self, *_):
            self.reads += 1
            class R:
                def all(self_): return [("ZZOLD", "ZZNEW")]
            return R()
    s = FakeSession()
    ticker_aliases.reset_cache()
    assert await ticker_aliases.alias_map(s, now=10.0) == {"ZZOLD": "ZZNEW"} and s.reads == 1      # a young clock still loads
    assert await ticker_aliases.alias_map(s, now=200.0) == {"ZZOLD": "ZZNEW"} and s.reads == 1     # inside the window: cached
    assert await ticker_aliases.alias_map(s, now=10.0 + ticker_aliases.CACHE_SECONDS + 1) and s.reads == 2   # past it: reloaded
    ticker_aliases.reset_cache()
    assert await ticker_aliases.alias_map(s, now=12.0) and s.reads == 3                             # a reset forces the next read
    ticker_aliases.reset_cache()


@pytest.mark.asyncio
async def test_rename_keeps_the_id_moves_every_symbol_column_rewrites_metadata_keys_and_redirects():
    old, new = "ZZOLD", "ZZNEW"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Rename test', true)"), {"s": old})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": old})).scalar()
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2026-10-01', 'sec_zz', 10, 1, 1, 0, now())"), {"s": old})
            await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, '{}', now())"), {"k": f"chain:{old}:2026-10-16"})
            await s.commit()
        async with ScriptSessionLocal() as s:
            changed = await rename_symbol(s, old, new, date(2026, 10, 6), "test")
            await s.commit()
        assert changed["tickers"] == 1 and changed["price_bars_shadow"] == 1 and changed["system_metadata keys"] == 1 and changed["ticker_aliases"] == 1
        async with ScriptSessionLocal() as s:
            assert (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": new})).scalar() == tid
            assert (await s.execute(text("SELECT count(*) FROM system_metadata WHERE key = :k"), {"k": f"chain:{new}:2026-10-16"})).scalar() == 1
            ticker_aliases.reset_cache()
            assert await ticker_aliases.resolve_symbol(s, old) == new
            with pytest.raises(ValueError):
                await rename_symbol(s, "AAPL", new, date(2026, 10, 6), "onto a live symbol")
        assert ticker_aliases.redirect_path(f"/api/v1/tickers/quote/{old}", {old: new}) == f"/api/v1/tickers/quote/{new}"
        assert ticker_aliases.redirect_path("/api/v1/tickers/quote/AAPL", {old: new}) is None
        assert "price_bars_shadow" in await symbol_tables(s) and "ticker_aliases" not in await symbol_tables(s)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM system_metadata WHERE key IN (:a, :b)"), {"a": f"chain:{old}:2026-10-16", "b": f"chain:{new}:2026-10-16"})
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol IN (:a, :b)"), {"a": old, "b": new})
            await s.execute(text("DELETE FROM ticker_aliases WHERE old_symbol = :s"), {"s": old})
            await s.execute(text("DELETE FROM tickers WHERE symbol IN (:a, :b)"), {"a": old, "b": new})
            await s.commit()
        ticker_aliases.reset_cache()


@pytest.mark.asyncio
async def test_symbol_matches_record_errors_when_intrinio_renamed_and_the_build_follows():
    sym = "ZZSYM"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Symbol test', true)"), {"s": sym})
            await s.execute(text("INSERT INTO security_records (symbol, intrinio_security_id, valid_from, role, source, intrinio_ticker) VALUES (:s, 'sec_zz', '2020-01-02', 'current', 'intrinio', 'ZZSYN')"), {"s": sym})
            await s.commit()
        r = (await run_checks([check_symbol_matches_record]))[0]
        assert r.level == ERROR and f"{sym}: Intrinio record sec_zz trades as ZZSYN" in r.rows
        assert "detect_rename(sym, stored_ids.get(sym), current, all_symbols - {sym}, stored_ids)" in inspect.getsource(bsr.main)
        assert check_symbol_matches_record in CHECKS and check_delisting_signals in CHECKS and check_pending_repairs in CHECKS
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


@pytest.mark.asyncio
async def test_a_rename_onto_a_duplicate_row_of_the_same_security_absorbs_it_and_keeps_the_old_id():
    old, dup = "ZZKEEP", "ZZDUP"
    try:
        async with ScriptSessionLocal() as s:
            for sym, created in ((old, datetime(2026, 5, 27, tzinfo=timezone.utc)), (dup, datetime(2026, 8, 19, tzinfo=timezone.utc))):
                await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at) VALUES (gen_random_uuid(), :s, 'Dup test', true, :c)"), {"s": sym, "c": created})
                await s.execute(text("INSERT INTO security_records (symbol, intrinio_security_id, valid_from, role, source, intrinio_ticker, name) VALUES (:s, 'sec_dup', '2020-01-02', 'current', 'intrinio', :t, 'Dup Test Renamed')"), {"s": sym, "t": dup})
                await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2026-10-01', 'sec_dup', 10, 1, 1, 0, now())"), {"s": sym})
            await s.execute(text("INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, factor, split_ratio, dividend, fetched_at) VALUES (:s, '2026-01-02', 'sec_dup', 9, 1, 1, 0, now())"), {"s": old})   # the kept history begins before its events
            await s.execute(text("INSERT INTO iv_history (id, symbol, date, iv_source, atm_iv) VALUES (gen_random_uuid(), :s, '2026-09-30', 'courier', 0.3)"), {"s": old})
            await s.execute(text("INSERT INTO iv_history (id, symbol, date, iv_source, atm_iv) VALUES (gen_random_uuid(), :s, '2026-10-02', 'courier', 0.4)"), {"s": dup})     # only the duplicate has this one
            ids = dict((await s.execute(text("SELECT symbol, id FROM tickers WHERE symbol IN (:a, :b)"), {"a": old, "b": dup})).all())
            for sym, d in ((old, date(2026, 7, 30)), (dup, date(2026, 7, 30)), (dup, date(2026, 10, 1))):
                await s.execute(text("INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at) VALUES (gen_random_uuid(), :t, 'earnings', :d, 'x', 'finnhub', false, '{}', now(), now())"), {"t": ids[sym], "d": d})
                await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, event_id, pct_change_1d, created_at)
                                        SELECT gen_random_uuid(), :t, 'earnings', :d, e.id, 1.0, now() FROM events e WHERE e.ticker_id = :t AND e.event_date = :d"""), {"t": ids[sym], "d": d})
            await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, '{}', now()), (:k2, '{}', now())"), {"k": f"chain:{old}:2026-10-01", "k2": f"chain:{dup}:2026-10-01"})
            await s.commit()
        assert await unique_keys(s, "price_bars_shadow", "symbol") == [["date"]] and await unique_keys(s, "events", "ticker_id") == [["event_type", "event_date"]]
        async with ScriptSessionLocal() as s:
            changed = await rename_symbol(s, old, dup, date(2026, 10, 6), "test")
            await s.commit()
        assert changed["tickers dropped"] == 1 and changed["price_bars_shadow dropped"] == 1 and changed["iv_history moved"] == 1 and "historical_reactions refused (before first bar)" not in changed
        assert changed["events dropped"] == 1 and changed["events moved"] == 1 and changed["historical_reactions dropped"] == 1 and changed["historical_reactions moved"] == 1
        assert changed["system_metadata keys dropped (target exists)"] == 1 and changed["tickers"] == 1 and changed["tickers name"] == 1

        async with ScriptSessionLocal() as s:
            assert (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": dup})).scalar() == ids[old]       # the old row, renamed
            assert (await s.execute(text("SELECT name FROM tickers WHERE symbol = :s"), {"s": dup})).scalar() == "Dup Test Renamed"
            assert (await s.execute(text("SELECT count(*) FROM tickers WHERE symbol = :s"), {"s": old})).scalar() == 0
            assert (await s.execute(text("SELECT count(*) FROM iv_history WHERE symbol = :s"), {"s": dup})).scalar() == 2
            assert (await s.execute(text("SELECT count(*) FROM price_bars_shadow WHERE symbol = :s"), {"s": dup})).scalar() == 2
            ev = (await s.execute(text("SELECT event_date FROM events WHERE ticker_id = :t ORDER BY 1"), {"t": ids[old]})).scalars().all()
            assert [d.isoformat() for d in ev] == ["2026-07-30", "2026-10-01"]
            dangling = (await s.execute(text("SELECT count(*) FROM historical_reactions hr LEFT JOIN events e ON e.id = hr.event_id WHERE hr.ticker_id = :t AND e.id IS NULL"), {"t": ids[old]})).scalar()
            assert dangling == 0 and (await s.execute(text("SELECT count(*) FROM historical_reactions WHERE ticker_id = :t"), {"t": ids[old]})).scalar() == 2
            assert (await s.execute(text("SELECT count(*) FROM system_metadata WHERE key LIKE :k"), {"k": f"chain:{dup}:%"})).scalar() == 1
            ticker_aliases.reset_cache()
            assert await ticker_aliases.resolve_symbol(s, old) == dup
    finally:
        async with ScriptSessionLocal() as s:
            for sym in (old, dup):
                tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
                if tid:
                    await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id = :t"), {"t": tid})
                    await s.execute(text("DELETE FROM events WHERE ticker_id = :t"), {"t": tid})
                await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :k"), {"k": f"chain:{sym}:%"})
                for t in ("iv_history", "price_bars_shadow", "security_records"):
                    await s.execute(text(f"DELETE FROM {t} WHERE symbol = :s"), {"s": sym})
                await s.execute(text("DELETE FROM ticker_aliases WHERE old_symbol = :s OR symbol = :s"), {"s": sym})
                await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
        ticker_aliases.reset_cache()


def test_membership_is_judged_before_the_per_ticker_work_so_a_quiet_night_still_judges_it():
    src = inspect.getsource(seed_sp500.main)
    assert src.index("await apply_membership(candidates)") < src.index("if not to_process:")


# ── 2. idempotent nightly steps ──────────────────────────────────────────────

def test_the_nightly_recompute_acts_only_on_sourceless_rows_and_corrected_windows():
    where, params = rr.nightly_where(), rr.nightly_params()
    assert where.startswith("WHERE hr.price_source IS NULL OR (hr.event_date BETWEEN :c0_from AND :c0_to")
    assert params["c0_from"] == date(2021, 12, 31) - timedelta(days=12) and params["c0_to"] == date(2022, 1, 1)
    assert params["c1_from"] == date(2025, 1, 9) - timedelta(days=12) and params["c1_applied"].date() == date(2026, 10, 6)
    assert set(CALENDAR_CORRECTIONS) == {date(2021, 12, 31), date(2025, 1, 9)}
    labels = [label for label, _ in refresh.STEPS]
    assert labels.index("Analyst reaction stats") < labels.index("Recompute reactions (Intrinio)") < labels.index("Sector peer snapshot")
    assert labels.index("Split history") < labels.index("Reclassify spin-offs")
    assert dict(refresh.STEPS)["Recompute reactions (Intrinio)"][-1] == "--nightly" and dict(refresh.STEPS)["Reclassify spin-offs"][-1] == "--write"
    assert "price_computed_at = now()" in inspect.getsource(rr.run)


@pytest.mark.asyncio
async def test_pending_repairs_are_named_from_their_preconditions():
    r = (await run_checks([check_pending_repairs]))[0]
    assert r.level in (PASS, WARN)
    if r.level == WARN:
        assert all("python -m app.scripts." in row for row in r.rows)


# ── 3. the nightly on the New York clock, resumable ──────────────────────────

def test_the_slot_is_02_30_new_york_every_day_of_the_year():
    assert (nc.NIGHTLY_LOCAL_TIME.hour, nc.NIGHTLY_LOCAL_TIME.minute, nc.NIGHTLY_CLOCK) == (2, 30, "America/New_York")
    summer = nc.latest_slot(datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc))        # 03:00 EDT: today's slot was 02:30 EDT = 06:30Z
    assert summer.astimezone(timezone.utc) == datetime(2026, 7, 10, 6, 30, tzinfo=timezone.utc)
    winter = nc.latest_slot(datetime(2026, 12, 10, 7, 0, tzinfo=timezone.utc))       # 02:00 EST: before 02:30, so yesterday's slot (07:30Z)
    assert winter.astimezone(timezone.utc) == datetime(2026, 12, 9, 7, 30, tzinfo=timezone.utc)
    assert nc.slot_key(winter) == "2026-12-09"
    assert nc.nightly_due(datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc), "2026-07-09") and not nc.nightly_due(datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc), "2026-07-10")
    c = cad.cadence(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    assert c["nightly"]["local_time"] == "02:30" and c["nightly"]["clock"] == "America/New_York" and c["nightly"]["utc_today"] == "06:30Z"
    assert not hasattr(nc, "NIGHTLY_RUN_UTC_HOUR")


def test_a_resumed_run_starts_at_the_first_incomplete_step_and_logs_the_interruption():
    steps = [("a", ["x"]), ("b", ["x"]), ("c", ["x"]), ("d", ["x"])]
    assert refresh.steps_to_run(steps, {}) == steps
    assert refresh.steps_to_run(steps, {"a": "t", "b": "t"}) == steps[2:]
    assert refresh.steps_to_run(steps, {"a": "t", "c": "t"}) == steps[1:]          # c's stamp does not let it skip after b
    src = inspect.getsource(refresh.main)
    assert '"interrupted": True' in src and '"resumed_from"' in src and "_db_upsert(slot_progress_key(slot), json.dumps(done))" in src
    startup = inspect.getsource(__import__("app.startup", fromlist=["x"]))
    assert "functools.partial(pipeline.main, slot=nightly_slot)" in startup and "_KEY_LAST_REFRESHED, now_iso" not in startup

# shares alert_picks rows with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="picks")
