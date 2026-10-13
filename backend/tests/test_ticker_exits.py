"""Companies no longer trading: the stored reason's kind, the page's "no longer trades" line, the filing-sourced exits script,
and the validate check on inactive tickers."""
import inspect
from datetime import date

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import build_security_records, record_ticker_exits, seed_sp500
from app.scripts.validate_data import CHECKS, ERROR, check_inactive_ticker_state
from app.services import ticker_exits as tx

pytestmark = pytest.mark.xdist_group(name="ticker_exits")


def test_the_ea_line_reads_exactly_as_approved():
    reason = next(e["reason"] for e in record_ticker_exits.EXITS if e["symbol"] == "EA")
    assert tx.exit_line("Electronic Arts Inc.", reason, date(2026, 8, 4)) == \
        "Electronic Arts was taken private on August 4, 2026, and its stock no longer trades."


def test_only_a_kind_with_an_approved_line_gets_one():
    assert set(tx.EXIT_LINES) <= set(tx.NO_LONGER_TRADES)
    assert tx.exit_line("Acme Corp.", "delisted: last session 2026-09-01; no Intrinio price since 2026-09-01", date(2026, 9, 1)) is None   # held for approval
    assert tx.exit_line("Acme Corp.", "left the S&P 500 on 2026-10-06: missing", date(2026, 10, 6)) is None                             # still trades
    assert tx.exit_line("Acme Corp.", "taken private on 2026-08-04: x", None) is None                                                   # no date, no line
    assert tx.exit_line(None, "taken private on 2026-08-04: x", date(2026, 8, 4)) is None


def test_plain_name_drops_the_legal_suffix():
    assert tx.plain_name("Electronic Arts Inc.") == "Electronic Arts"
    assert tx.plain_name("AvalonBay Communities, Inc.") == "AvalonBay Communities"
    assert tx.plain_name("EchoStar Corporation") == "EchoStar"
    assert tx.plain_name("Apple") == "Apple"


def test_every_reason_writer_spells_a_known_prefix():
    assert tx.exit_kind("left the S&P 500 (first missing from the constituent list on 2026-10-06)") == tx.LEFT_INDEX   # the older wording
    assert 'f"left the S&P 500 on {today.isoformat()}' in inspect.getsource(seed_sp500.deactivate_index_leavers)
    assert 'reason = f"delisted: last session' in inspect.getsource(build_security_records.apply_delisting_rule)
    assert {tx.exit_kind(e["reason"]) for e in record_ticker_exits.EXITS} == {tx.TAKEN_PRIVATE, tx.MERGED, tx.TICKER_CHANGED}
    assert tx.exit_kind("went away") is None and tx.exit_kind(None) is None


def test_the_exits_plan_sets_membership_and_reason_and_holds_what_no_filing_dates():
    row = lambda sym, name, active=False: {"symbol": sym, "name": name, "is_active": active, "index_member": True, "inactive_reason": None, "inactive_since": None}
    stored = {"EA": row("EA", "Electronic Arts Inc."), "AVB": row("AVB", "AvalonBay Communities, Inc."), "SATS": row("SATS", "EchoStar Corporation")}
    succ = {"VMRK": row("VMRK", "Vivmark Residential", True), "ECHO": row("ECHO", "EchoStar Corporation", True)}
    plans = {p["symbol"]: p for p in record_ticker_exits.plan_rows(stored, succ)}
    assert all(p["set"]["index_member"] is False and p["set"]["inactive_reason"] for p in plans.values())
    assert plans["EA"]["alias"] is None and plans["EA"]["set"]["inactive_since"] == date(2026, 8, 4) and plans["EA"]["held"] == []
    assert plans["EA"]["line"] == "Electronic Arts was taken private on August 4, 2026, and its stock no longer trades."
    assert plans["AVB"]["alias"]["symbol"] == "VMRK" and plans["AVB"]["alias"]["renamed_on"] == date(2026, 8, 17) and plans["AVB"]["line"] is None
    assert plans["SATS"]["alias"] is None and plans["SATS"]["set"]["inactive_since"] is None and len(plans["SATS"]["held"]) == 2
    # a successor that is not stored, or not active, gets no alias
    gone = record_ticker_exits.plan_rows(stored, {})
    assert all(p["alias"] is None for p in gone) and any("not an active stored ticker" in h for p in gone for h in p["held"])


def test_every_exit_cites_an_accession_number():
    import re
    for e in record_ticker_exits.EXITS:
        assert re.search(r"\d{10}-\d{2}-\d{6}", e["reason"]), e["symbol"]


@pytest.mark.asyncio
async def test_validate_errors_on_an_inactive_index_member_or_a_missing_or_unknown_reason():
    assert check_inactive_ticker_state in CHECKS
    seeds = [("ZZEX1", True, "taken private on 2026-08-04: x"), ("ZZEX2", False, None), ("ZZEX3", False, "went away"),
             ("ZZEX4", False, "merged into VMRK on 2026-08-17: x")]
    try:
        async with ScriptSessionLocal() as s:
            for sym, member, why in seeds:
                await s.execute(text("""INSERT INTO tickers (id, symbol, name, is_active, index_member, inactive_reason)
                    VALUES (gen_random_uuid(), :s, 'Exit test', false, :m, :w) ON CONFLICT (symbol) DO NOTHING"""), {"s": sym, "m": member, "w": why})
            await s.commit()
        async with ScriptSessionLocal() as s:
            r = await check_inactive_ticker_state(s)
        mine = sorted(x for x in r.rows if x.startswith("ZZEX"))
        assert r.level == ERROR
        assert mine == ["ZZEX1: still index_member", "ZZEX2: no inactive_reason", "ZZEX3: reason in no known wording"]
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM tickers WHERE symbol LIKE 'ZZEX%'"))
            await s.commit()


@pytest.mark.asyncio
async def test_the_ticker_api_gives_an_inactive_no_successor_stock_its_exit_and_last_stored_close():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("""INSERT INTO tickers (id, symbol, name, is_active, index_member, inactive_reason, inactive_since, market_cap)
                VALUES (gen_random_uuid(), 'ZZEX5', 'Zed Games Inc.', false, false, 'taken private on 2026-08-04: x', '2026-08-04', 5000000000),
                       (gen_random_uuid(), 'ZZEX6', 'Zed Bars Inc.', false, false, 'taken private on 2026-08-04: x', '2026-08-04', NULL),
                       (gen_random_uuid(), 'ZZEX7', 'Zed Left Inc.', false, false, 'left the S&P 500 on 2026-10-06: x', '2026-10-06', NULL)"""))
            await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, close, fetched_at)
                VALUES ('ZZEX6', '2026-08-03', 'sec_test', 41.5, now()), ('ZZEX6', '2026-08-04', 'sec_test', 42.25, now())"""))
            await s.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            five = (await c.get("/api/v1/tickers/by-symbol/ZZEX5")).json()
            six = (await c.get("/api/v1/tickers/by-symbol/ZZEX6")).json()
            seven = (await c.get("/api/v1/tickers/by-symbol/ZZEX7")).json()
        assert five["exit"] == {"kind": "taken_private", "line": "Zed Games was taken private on August 4, 2026, and its stock no longer trades.",
                                "since": "2026-08-04", "last_close": None, "last_close_date": None}
        assert six["exit"]["last_close"] == 42.25 and six["exit"]["last_close_date"] == "2026-08-04"
        assert seven["exit"] is None
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol LIKE 'ZZEX%'"))
            await s.execute(text("DELETE FROM tickers WHERE symbol LIKE 'ZZEX%'"))
            await s.commit()
