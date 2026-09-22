"""A refused earnings date is recorded, listed by validate, and swapped only on SEC evidence."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.ticker import Ticker
from app.scripts.seed_historical_reactions import upsert_reaction
from app.scripts.validate_data import PASS, WARN, check_refused_earnings_dates
from app.services.refusal_evidence import (
    NO_ACCEPTANCE, SUPPORTS_BLOCKING, SUPPORTS_BOTH, SUPPORTS_NEITHER, SUPPORTS_REFUSED, support,
)

D = date


def _utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_acceptance_supports_the_date_it_explains():
    # 8-K accepted 2026-07-31 08:05 ET (12:05 UTC): explains 2026-07-31 (pre-open) and 2026-07-30 (after close)
    refused, blocking = D(2026, 7, 31), D(2026, 7, 29)
    assert support("X", _utc(2026, 7, 31, 12, 5), refused, blocking) == SUPPORTS_REFUSED
    assert support("X", _utc(2026, 7, 29, 21, 30), refused, blocking) == SUPPORTS_BLOCKING   # 17:30 ET on the 29th
    assert support("X", _utc(2026, 7, 31, 12, 5), D(2026, 7, 31), D(2026, 7, 30)) == SUPPORTS_BOTH
    assert support("X", _utc(2026, 8, 10, 12, 5), refused, blocking) == SUPPORTS_NEITHER
    assert support("X", None, refused, blocking) == NO_ACCEPTANCE


class _Rollback(Exception):
    pass


@pytest.mark.asyncio
async def test_refusal_is_recorded_counted_and_listed():
    async def body():
        async with ScriptSessionLocal() as s:
            async with s.begin():
                tid = await s.scalar(text("""INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at)
                    VALUES (gen_random_uuid(), 'ZZREF', 'Refusal test', true, now(), now()) RETURNING id"""))
                ticker = Ticker(id=tid, symbol="ZZREF")
                base = {"pct_change_1d": Decimal("1.0"), "eps_estimate": Decimal("1.00"), "eps_actual": Decimal("1.10")}
                assert await upsert_reaction(s, ticker, D(2026, 7, 29), dict(base)) is True
                # a second date 2 days later is refused, twice
                assert await upsert_reaction(s, ticker, D(2026, 7, 31), dict(base)) is None
                assert await upsert_reaction(s, ticker, D(2026, 7, 31), dict(base)) is None
                rec = (await s.execute(text(
                    "SELECT refused_date, blocking_row_date, times_seen, source FROM refused_earnings_dates WHERE ticker_id = :t"
                ), {"t": tid})).one()
                assert rec == (D(2026, 7, 31), D(2026, 7, 29), 2, "yahoo")

                out = await check_refused_earnings_dates(s)
                assert out.level == WARN
                line = next(r for r in out.rows if r.startswith("ZZREF"))
                assert "offered 2026-07-31, refused by the 2026-07-29 row" in line and "no SEC acceptance" in line

                # with the blocking row's 8-K accepted pre-open on the 31st, the line says the refused date is supported
                await s.execute(text("""INSERT INTO earnings_report_timing (id, ticker_id, event_date, timing, source, acceptance_datetime)
                    VALUES (gen_random_uuid(), :t, :d, 'unknown', 'edgar', :a)"""),
                    {"t": tid, "d": D(2026, 7, 29), "a": _utc(2026, 7, 31, 12, 5)})
                line = next(r for r in (await check_refused_earnings_dates(s)).rows if r.startswith("ZZREF"))
                assert "supports the refused date" in line
                raise _Rollback

    with pytest.raises(_Rollback):
        await body()


def test_repair_never_swaps_without_sec_evidence():
    src = Path(__file__).resolve().parents[1].joinpath("app/scripts/repair_refused_dates.py").read_text()
    assert "if verdict != SUPPORTS_REFUSED:" in src and "no swap" in src
    assert "--write" in src and "delete(RefusedEarningsDate)" in src
