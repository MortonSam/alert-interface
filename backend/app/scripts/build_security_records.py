"""Resolve every active ticker to its Intrinio security record, by id, and keep the map fresh.

For each active ticker: one request to /securities/{ticker}; the current row is written from it, the
predecessor rows and stored_history rows come from services/security_records (data). Delisting is a rule, not a
list: a ticker whose current record has no Intrinio price for more than two sessions, is inactive at Intrinio, and
is absent from the constituent list is marked inactive with the date and reason in the outcome (rows kept, hidden
at read time). A record that comes back under a new ticker is a rename, applied in place with an alias. Every refresh also records what Intrinio returned (figi_seen,
last_price_date, checked_at) on the current row, which the validate checks security_record_coverage
and figi_change read without touching the network.

Dry run by default: prints what it would write. --write applies. The nightly runs it with --write.

Usage
-----
    python -m app.scripts.build_security_records
    python -m app.scripts.build_security_records --write
    python -m app.scripts.build_security_records --write --symbols=MU,CAT
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.security_record import SecurityRecord
from app.models.ticker import Ticker
from app.services.intrinio_client import IntrinioAuthError, IntrinioClient
from app.services.price_bars_shadow import BENCHMARKS
from app.services.security_records import CURRENT, Record, plan_records
from app.services.ticker_rename import detect_rename, rename_symbol
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Security records (Intrinio)"


async def upsert(session, rows: list[Record], seen: dict) -> tuple[int, int, bool]:
    """Write a symbol's rows. Returns (inserted, updated, figi_changed)."""
    inserted = updated = 0
    changed = False
    existing = {r.valid_from: r for r in (await session.execute(
        select(SecurityRecord).where(SecurityRecord.symbol == rows[0].symbol))).scalars().all()}
    now = datetime.now(timezone.utc)
    for r in rows:
        row = existing.get(r.valid_from)
        if row is None:
            row = SecurityRecord(symbol=r.symbol, valid_from=r.valid_from)
            session.add(row)
            inserted += 1
        else:
            updated += 1
        if row.role == CURRENT and row.figi and r.figi and row.figi != r.figi:
            changed = True          # Intrinio moved the ticker to a new record: the check reports it, the stored FIGI stays
        row.intrinio_security_id = r.intrinio_security_id
        row.composite_figi = r.composite_figi
        row.name = r.name
        row.valid_to = r.valid_to
        row.role = r.role
        row.source = r.source
        if row.figi is None:
            row.figi = r.figi
        if r.role == CURRENT:
            row.intrinio_ticker = seen.get("ticker")
            row.intrinio_active = seen.get("active")
            row.figi_seen = seen.get("figi")
            lp = seen.get("last_stock_price")
            row.last_price_date = date.fromisoformat(lp) if isinstance(lp, str) else lp
            row.checked_at = now
    return inserted, updated, changed


STALE_SESSIONS_FOR_DELISTING = 2        # a current record missing this many completed sessions (today excluded) is stale


def delisting_signals(last_price_date, intrinio_active, index_member, today) -> list[str]:
    """The three signs a stock stopped trading, in words; all three together delist the ticker, two make validate ERROR."""
    from app.services.trading_calendar import sessions_after
    out = []
    if last_price_date is not None and sessions_after(last_price_date, today) >= STALE_SESSIONS_FOR_DELISTING:
        out.append(f"no Intrinio price since {last_price_date.isoformat()}")
    if intrinio_active is False:
        out.append("Intrinio marks the record inactive")
    if index_member is False:
        out.append("absent from the constituent list")
    return out


async def apply_delisting_rule(session, today: date) -> dict[str, dict]:
    """Mark inactive every active ticker whose current record shows all three signals; close its record on the last
    price date. Returns {symbol: {date, reason}} for the tickers flipped tonight."""
    rows = (await session.execute(text("""
        SELECT t.id, t.symbol, t.index_member, sr.last_price_date, sr.intrinio_active, sr.id AS record_id
        FROM tickers t JOIN security_records sr ON sr.symbol = t.symbol AND sr.role = 'current'
        WHERE t.is_active"""))).all()
    out: dict[str, dict] = {}
    for r in rows:
        signals = delisting_signals(r.last_price_date, r.intrinio_active, r.index_member, today)
        if len(signals) == 3:
            reason = f"delisted: last session {r.last_price_date.isoformat()}; " + "; ".join(signals)
            await session.execute(text("UPDATE tickers SET is_active = false, inactive_reason = :why, inactive_since = :d WHERE id = :id"),
                                  {"why": reason, "d": r.last_price_date, "id": r.id})
            await session.execute(text("UPDATE security_records SET valid_to = :d WHERE id = :rid AND valid_to IS NULL"), {"d": r.last_price_date, "rid": r.record_id})
            out[r.symbol] = {"date": r.last_price_date.isoformat(), "reason": reason}
            print(f"  {r.symbol}: inactive; {reason}", flush=True)
    return out


async def main(argv: list[str]) -> int:
    write = "--write" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    async with ScriptSessionLocal() as session:
        symbols = list((await session.execute(select(Ticker.symbol).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    symbols = sorted(set(symbols) | set(BENCHMARKS))     # SPY gives the seeder its session calendar
    async with ScriptSessionLocal() as session:
        stored_ids = dict((await session.execute(text("SELECT symbol, intrinio_security_id FROM security_records WHERE role = 'current'"))).all())
        all_symbols = set((await session.execute(text("SELECT symbol FROM tickers"))).scalars().all())
    if only:
        symbols = [s for s in symbols if s in {x.strip().upper() for x in only.split(",")}]
    client = IntrinioClient()
    resolved: list[str] = []
    missing: list[str] = []
    figi_changes: list[str] = []
    renamed: dict[str, dict] = {}
    inserted = updated = 0
    try:
        for sym in symbols:
            try:
                current = await client._get(f"/securities/{sym}", {})
            except IntrinioAuthError as exc:
                print(f"  Intrinio refused the key: {exc}", flush=True)
                await record_step_fields(STEP_LABEL, {"error": str(exc)[:200], "resolved": 0})
                return 1
            except Exception as exc:
                missing.append(f"{sym}: {exc}")
                continue
            if not current or not current.get("id"):
                missing.append(f"{sym}: no record")
                continue
            # the same record under a new ticker is a rename: the ticker row keeps its id and history, the old symbol becomes an alias
            new_symbol = detect_rename(sym, stored_ids.get(sym), current, all_symbols - {sym}, stored_ids)
            if new_symbol and write:
                async with ScriptSessionLocal() as session:
                    changed = await rename_symbol(session, sym, new_symbol, date.today(), f"Intrinio record {current['id']} now trades as {new_symbol}",
                                                  name=current.get("name"))
                    await session.commit()
                renamed[sym] = {"to": new_symbol, "record": current["id"], "changed": changed}
                all_symbols.discard(sym); all_symbols.add(new_symbol)
                print(f"  {sym} -> {new_symbol}: renamed in place (record {current['id']}); {changed}", flush=True)
                sym = new_symbol
            elif new_symbol:
                renamed[sym] = {"to": new_symbol, "record": current["id"], "dry_run": True}
            rows = plan_records(sym, current)
            resolved.append(sym)
            if write:
                async with ScriptSessionLocal() as session:
                    ins, upd, changed = await upsert(session, rows, current)
                    await session.commit()
                inserted += ins
                updated += upd
                if changed:
                    figi_changes.append(sym)
            else:
                for r in rows:
                    print(f"  {sym:6} {r.role:14} {r.intrinio_security_id or '-':12} {r.figi or '-':13} {r.valid_from.isoformat()}..{r.valid_to.isoformat() if r.valid_to else 'open'}")
    finally:
        await client.close()
    print(f"\n{'─' * 60}\n  {'written' if write else 'dry run'}: {len(resolved)} resolved, {len(missing)} missing, "
          f"{inserted} inserted, {updated} updated, {len(figi_changes)} FIGI change(s); {client.request_count} request(s)\n{'─' * 60}")
    for m in missing[:20]:
        print("   missing:", m)
    deactivated: dict[str, dict] = {}
    if write:
        async with ScriptSessionLocal() as session:
            deactivated = await apply_delisting_rule(session, date.today())
            await session.commit()
        await record_step_fields(STEP_LABEL, {"resolved": len(resolved), "missing": missing[:50], "inserted": inserted, "updated": updated,
                                              "figi_changes": figi_changes, "requests": client.request_count,
                                              "renamed": renamed, "deactivated_this_run": deactivated, "error": None})
    elif renamed:
        print("  renames the write would apply:", renamed)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
