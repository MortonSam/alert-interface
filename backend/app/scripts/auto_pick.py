"""Nightly auto-picker: evaluate active tickers with upcoming earnings and generate picks.

Every evaluation is persisted to alert_pick_evaluations — nothing is cherry-picked,
refusals are recorded.

Usage:
    python -m app.scripts.auto_pick            # real run
    python -m app.scripts.auto_pick --dry-run  # skip LLM + persist, print what would happen
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.alert_pick import AlertPick, AlertPickEvaluation
from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.routers.thesis import compute_alert_pick
from app.services import chain_store

MAX_NEW_PER_NIGHT = 3
MAX_OPEN_TOTAL = 10
MAX_DRAFT_ATTEMPTS = 6


async def _check_chain_freshness(session, sym: str) -> tuple[bool, str | None]:
    """Check if a fresh options chain exists for sym in system_metadata.

    Returns (is_fresh, chain_last_trade_or_none).
    Fresh means: chain exists AND chain_last_trade is ≤ 2 trading days old.
    """
    exps = await chain_store.get_ingested_expirations(session, sym)
    if not exps:
        return False, None

    # Check the most recent expiration's chain
    for exp in reversed(exps):
        result = await chain_store.get_chain(session, sym, exp)
        if result:
            _, chain_last_trade = result
            return chain_store.is_fresh(chain_last_trade), chain_last_trade
    return False, None


async def _run(dry_run: bool = False) -> int:
    today = date.today()
    horizon = today + timedelta(days=7)

    async with AsyncSessionLocal() as session:
        # ── Count currently open picks ────────────────────────────────────────
        open_count = (await session.execute(
            select(func.count()).select_from(AlertPick).where(AlertPick.status == "open")
        )).scalar_one()

        if open_count >= MAX_OPEN_TOTAL:
            print(f"[auto-pick] {open_count} open picks (cap={MAX_OPEN_TOTAL}). Skipping.")
            return 0

        # ── Find candidates: active tickers with earnings in next 7 days ─────
        candidates = (await session.execute(
            select(Ticker.symbol, func.min(Event.event_date).label("next_earnings"))
            .join(Event, Event.ticker_id == Ticker.id)
            .where(
                Ticker.is_active.is_(True),
                Event.event_type == EventType.EARNINGS,
                Event.event_date >= today,
                Event.event_date <= horizon,
            )
            .group_by(Ticker.symbol)
            .order_by(func.min(Event.event_date))
        )).all()

        if not candidates:
            print("[auto-pick] No candidates with earnings in next 7 days.")
            return 0

        print(f"[auto-pick] {len(candidates)} candidates, {open_count} open picks, dry_run={dry_run}")

        new_picks = 0
        draft_attempts = 0
        for row in candidates:
            sym = row.symbol
            next_earnings = row.next_earnings

            # ── Cap check ─────────────────────────────────────────────────────
            if new_picks >= MAX_NEW_PER_NIGHT:
                if not dry_run:
                    _log_evaluation(session, sym, "cap_reached", note=f"MAX_NEW_PER_NIGHT={MAX_NEW_PER_NIGHT}")
                print(f"  {sym} (earnings {next_earnings}): cap_reached")
                continue

            if open_count + new_picks >= MAX_OPEN_TOTAL:
                if not dry_run:
                    _log_evaluation(session, sym, "cap_reached", note=f"MAX_OPEN_TOTAL={MAX_OPEN_TOTAL}")
                print(f"  {sym} (earnings {next_earnings}): cap_reached (total)")
                continue

            if draft_attempts >= MAX_DRAFT_ATTEMPTS:
                if not dry_run:
                    _log_evaluation(session, sym, "cap_reached", note="draft attempts")
                print(f"  {sym} (earnings {next_earnings}): cap_reached (draft attempts)")
                continue

            # ── Chain freshness pre-check ─────────────────────────────────────
            is_fresh, chain_as_of = await _check_chain_freshness(session, sym)
            if not is_fresh:
                note = f"as_of={chain_as_of}" if chain_as_of else "no chain"
                if not dry_run:
                    _log_evaluation(session, sym, "no_fresh_chain", note=note)
                print(f"  {sym} (earnings {next_earnings}): no_fresh_chain ({note})")
                continue

            # ── Evaluate ──────────────────────────────────────────────────────
            try:
                result = await compute_alert_pick(sym, session, source="nightly", dry_run=dry_run)
                outcome = result["outcome"]
                leans = result["leans"]
                pick_id = result.get("pick_id")
                note = result.get("note")

                # Count any candidate that reached the LLM stage
                if outcome == "picked":
                    new_picks += 1
                    draft_attempts += 1
                elif outcome != "mixed_evidence" and outcome != "open_pick_exists":
                    # errored during draft — still counts as a draft attempt
                    draft_attempts += 1

                if not dry_run:
                    leans_dump = [l.model_dump() for l in leans] if leans else None
                    _log_evaluation(
                        session, sym, outcome,
                        leans=leans_dump, pick_id=pick_id, note=note,
                    )

                leans_summary = " ".join(f"{l.signal[0]}={l.direction[:3]}" for l in leans) if leans else ""
                print(f"  {sym} (earnings {next_earnings}): {outcome} [{leans_summary}]")

            except HTTPException as exc:
                # Draft-path errors (422 stale chain, 502 AI failure) count as draft attempts
                draft_attempts += 1
                if not dry_run:
                    _log_evaluation(session, sym, "error", note=f"HTTP {exc.status_code}: {exc.detail}")
                print(f"  {sym} (earnings {next_earnings}): error — {exc.detail}")

            except Exception as exc:
                tb = traceback.format_exc()
                draft_attempts += 1
                if not dry_run:
                    _log_evaluation(session, sym, "error", note=f"{type(exc).__name__}: {exc}")
                print(f"  {sym} (earnings {next_earnings}): error — {exc}\n{tb}")

        if not dry_run:
            await session.commit()

        # ── Summary ───────────────────────────────────────────────────────────
        print(
            f"\n[auto-pick] Done. {new_picks} new picks, "
            f"{open_count + new_picks} total open, "
            f"{len(candidates)} evaluated, "
            f"{draft_attempts} draft attempts."
        )
    return 0


def _log_evaluation(
    session,
    symbol: str,
    outcome: str,
    leans: list[dict] | None = None,
    pick_id=None,
    note: str | None = None,
) -> None:
    """Add an AlertPickEvaluation row (uncommitted — caller commits)."""
    session.add(AlertPickEvaluation(
        symbol=symbol,
        source="nightly",
        outcome=outcome,
        leans=leans,
        alert_pick_id=pick_id,
        note=note,
    ))


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return asyncio.run(_run(dry_run=dry_run))


if __name__ == "__main__":
    sys.exit(main())
