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
from sqlalchemy import Date as SADate, func, select

from app.constants import LEDGER_START
from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.alert_pick import AlertPick, AlertPickEvaluation
from app.models.credit_shadow_pick import CreditShadowPick
from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.routers.thesis import compute_alert_pick
from app.services import chain_store
from app.services.trading_calendar import nth_trading_day_after

from decimal import Decimal

MAX_NEW_PER_NIGHT = 3
MAX_OPEN_TOTAL = 10
MAX_DRAFT_ATTEMPTS = 6


def _build_v2_fields(result: dict) -> dict:
    """Extract v2 worksheet columns from a compute_alert_pick result.

    Always returns a dict with at least verdict. Receipt fields are
    populated whenever the receipt is present (picks AND refusals).
    """
    receipt = result.get("receipt")
    fields: dict = {}
    if receipt:
        if receipt.get("momentum_20d") is not None:
            fields["momentum_20d"] = Decimal(str(round(receipt["momentum_20d"], 2)))
        if receipt.get("n_comparable") is not None:
            fields["prior_n"] = int(receipt["n_comparable"])
        if receipt.get("expected_pct") is not None:
            fields["expected_move_pct"] = Decimal(str(receipt["expected_pct"]))
        if receipt.get("implied_pct") is not None:
            fields["implied_move_pct"] = Decimal(str(receipt["implied_pct"]))
    fields["verdict"] = _build_verdict(result, receipt)
    return fields


def _build_verdict(result: dict, receipt: dict | None) -> str:
    """Build a plain-English verdict string for the v2 worksheet.

    Outcome codes are short DB keys; verdict is the human-readable text
    shown on the Desk worksheet.
    """
    outcome = result.get("outcome", "")
    gate_reason = receipt.get("gate_reason") if receipt else None

    if outcome == "no_features":
        return "Passed, no features available"
    if outcome == "no_fresh_chain":
        return "Refused, no fresh chain"
    if outcome == "vol_gate":
        if gate_reason:
            return f"Refused, {gate_reason}"
        return "Refused, IV too high"
    if outcome == "insufficient_history":
        n = receipt.get("n_comparable", 0) if receipt else 0
        return f"Passed, {n or 0} prior events (needs 8)"
    if outcome == "momentum_gate":
        m = receipt.get("momentum_20d") if receipt else None
        if m is not None:
            return f"Passed, momentum {m:+.0f}% (needs <= -10%)"
        return "Passed, no momentum data"
    if outcome == "picked":
        structure = result.get("structure")
        if structure:
            ls = structure.get("long_strike", "")
            ss = structure.get("short_strike", "")
            exp = structure.get("expiration", "")
            return f"Picked, bull call spread {ls}/{ss}, {exp}"
        return "Picked"
    if outcome == "structure_failed":
        return "Refused, structure failed"
    if outcome == "open_pick_exists":
        return "Passed, open pick exists"
    if outcome == "cap_reached":
        return "Passed, cap reached"
    if outcome == "error":
        return "Error"
    return outcome


async def _build_no_chain_fields(session, sym: str) -> dict:
    """Build v2 worksheet fields for a no-chain refusal.

    Runs compute_live_features to get momentum, prior_n, and expected
    move -- everything that doesn't require a chain. implied_move_pct
    stays null.
    """
    from app.services.ivy_v2 import compute_live_features, compute_expected_move

    fields: dict = {"verdict": "Refused, no fresh chain"}
    try:
        live = await compute_live_features(sym, session)
        if live is not None:
            if live.momentum_20d is not None:
                fields["momentum_20d"] = Decimal(str(round(float(live.momentum_20d), 2)))
            if live.prior_n is not None:
                fields["prior_n"] = int(live.prior_n)
            expected = compute_expected_move(live)
            if expected is not None:
                fields["expected_move_pct"] = Decimal(str(round(expected, 2)))
    except Exception:
        pass  # best-effort; verdict alone is sufficient
    return fields


def _leg_mid(row: dict) -> float:
    """Compute mid price for a single option leg (same rule as close_alert_picks)."""
    bid = row.get("bid") or 0.0
    ask = row.get("ask") or 0.0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if bid == 0 and ask > 0:
        return ask / 2.0
    return 0.0


async def _build_iron_condor(session, sym: str, event_date: date, receipt: dict) -> CreditShadowPick | None:
    """Record a hypothetical iron condor from a vol_gate refusal. Returns None if structure can't be built."""
    expected_pct = receipt.get("expected_pct")
    implied_pct = receipt.get("implied_pct")
    if expected_pct is None or implied_pct is None:
        return None

    # Pick expiration
    exp = await chain_store.pick_expiration(session, sym, event_date.isoformat())
    if exp is None:
        return None

    # Get chain
    result = await chain_store.get_chain(session, sym, exp)
    if result is None:
        return None
    chain_data, _ = result
    spot = chain_data.get("underlying_price")
    if spot is None or spot <= 0:
        return None

    # Compute targets: spot * (1 +/- 1.25 * expected_pct/100)
    put_target = spot * (1 - 1.25 * expected_pct / 100)
    call_target = spot * (1 + 1.25 * expected_pct / 100)

    puts = sorted(chain_data.get("puts", []), key=lambda r: r.get("strike", 0))
    calls = sorted(chain_data.get("calls", []), key=lambda r: r.get("strike", 0))
    if not puts or not calls:
        return None

    # Short put = max strike <= put_target
    short_put_row = None
    for row in reversed(puts):
        if row.get("strike", 0) <= put_target:
            short_put_row = row
            break
    if short_put_row is None:
        return None

    # Long put = next strike below short put
    sp_strike = short_put_row["strike"]
    long_put_row = None
    for row in reversed(puts):
        if row.get("strike", 0) < sp_strike:
            long_put_row = row
            break
    if long_put_row is None:
        return None

    # Short call = min strike >= call_target
    short_call_row = None
    for row in calls:
        if row.get("strike", 0) >= call_target:
            short_call_row = row
            break
    if short_call_row is None:
        return None

    # Long call = next strike above short call
    sc_strike = short_call_row["strike"]
    long_call_row = None
    for row in calls:
        if row.get("strike", 0) > sc_strike:
            long_call_row = row
            break
    if long_call_row is None:
        return None

    # Compute mids
    sp_mid = _leg_mid(short_put_row)
    sc_mid = _leg_mid(short_call_row)
    lp_mid = _leg_mid(long_put_row)
    lc_mid = _leg_mid(long_call_row)

    credit = (sp_mid + sc_mid) - (lp_mid + lc_mid)
    if credit <= 0:
        return None

    put_wing = sp_strike - long_put_row["strike"]
    call_wing = long_call_row["strike"] - sc_strike
    max_loss = max(put_wing, call_wing) - credit
    if max_loss <= 0:
        return None

    exit_dt = nth_trading_day_after(event_date, 5)

    return CreditShadowPick(
        symbol=sym,
        event_date=event_date,
        spot=Decimal(str(round(spot, 4))),
        expected_pct=Decimal(str(round(expected_pct, 4))),
        implied_pct=Decimal(str(round(implied_pct, 4))),
        short_put_strike=Decimal(str(round(sp_strike, 4))),
        short_call_strike=Decimal(str(round(sc_strike, 4))),
        long_put_strike=Decimal(str(round(long_put_row["strike"], 4))),
        long_call_strike=Decimal(str(round(long_call_row["strike"], 4))),
        expiration=exp,
        credit_received=Decimal(str(round(credit, 4))),
        max_loss=Decimal(str(round(max_loss, 2))),
        exit_date=exit_dt,
    )


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
    # 1-5 trading days ~ next 7 calendar days; exclude today (event day
    # itself is too late for momentum to be measured into the report).
    horizon = today + timedelta(days=7)

    async with AsyncSessionLocal() as session:
        # ── Count currently open v2 picks (season 2, post-LEDGER_START only) ──
        open_count = (await session.execute(
            select(func.count()).select_from(AlertPick).where(
                AlertPick.status == "open",
                AlertPick.season == 2,
                func.cast(AlertPick.generated_at, SADate) >= LEDGER_START,
            )
        )).scalar_one()

        # ── Find candidates: active tickers with earnings in 1-5 trading days
        candidates = (await session.execute(
            select(Ticker.symbol, func.min(Event.event_date).label("next_earnings"))
            .join(Event, Event.ticker_id == Ticker.id)
            .where(
                Ticker.is_active.is_(True),
                Event.event_type == EventType.EARNINGS,
                Event.event_date > today,
                Event.event_date <= horizon,
            )
            .group_by(Ticker.symbol)
            .order_by(func.min(Event.event_date))
        )).all()

        if not candidates:
            print("[auto-pick] No candidates with earnings in next 1-5 trading days.")
            return 0

        print(f"[auto-pick] {len(candidates)} candidates, {open_count} open v2 picks, dry_run={dry_run}")

        new_picks = 0
        draft_attempts = 0
        for row in candidates:
            sym = row.symbol
            next_earnings = row.next_earnings
            cap_hit = False

            # ── Cap check (never skips evaluation -- just blocks persisting) ──
            if new_picks >= MAX_NEW_PER_NIGHT:
                cap_hit = True
            elif open_count + new_picks >= MAX_OPEN_TOTAL:
                cap_hit = True
            elif draft_attempts >= MAX_DRAFT_ATTEMPTS:
                cap_hit = True

            # ── Chain freshness pre-check ─────────────────────────────────────
            is_fresh, chain_as_of = await _check_chain_freshness(session, sym)
            if not is_fresh:
                note = f"as_of={chain_as_of}" if chain_as_of else "no chain"
                if not dry_run:
                    # Still evaluate to populate worksheet fields (without chain)
                    v2_fields = await _build_no_chain_fields(session, sym)
                    _log_evaluation(session, sym, "no_fresh_chain", note=note,
                                   v2_fields=v2_fields)
                print(f"  {sym} (earnings {next_earnings}): no_fresh_chain ({note})")
                continue

            # ── Evaluate (always -- cap only blocks persisting the pick) ──────
            try:
                result = await compute_alert_pick(
                    sym, session, source="nightly",
                    dry_run=dry_run or cap_hit,
                )
                outcome = result["outcome"]
                leans = result["leans"]
                pick_id = result.get("pick_id")
                note = result.get("note")

                # If cap blocked a would-be pick, record it as cap_reached
                if cap_hit and outcome == "picked":
                    outcome = "cap_reached"
                    pick_id = None

                # Count picks and LLM draft attempts
                if outcome == "picked":
                    new_picks += 1
                    draft_attempts += 1

                if not dry_run:
                    leans_dump = [l.model_dump() for l in leans] if leans else None
                    v2_fields = _build_v2_fields(result)
                    _log_evaluation(
                        session, sym, outcome,
                        leans=leans_dump, pick_id=pick_id, note=note,
                        v2_fields=v2_fields,
                    )

                    # Record hypothetical iron condor on vol_gate (idempotent upsert)
                    if outcome == "vol_gate":
                        receipt = result.get("receipt")
                        if receipt:
                            ic = await _build_iron_condor(session, sym, next_earnings, receipt)
                            if ic is not None:
                                from sqlalchemy.dialects.postgresql import insert as pg_insert
                                ic_values = {
                                    c.name: getattr(ic, c.name)
                                    for c in CreditShadowPick.__table__.columns
                                    if c.name != "id"
                                }
                                ic_stmt = (
                                    pg_insert(CreditShadowPick)
                                    .values(**ic_values)
                                    .on_conflict_do_nothing(
                                        constraint="uq_credit_shadow_picks_symbol_event_date",
                                    )
                                )
                                await session.execute(ic_stmt)

                leans_summary = " ".join(f"{l.signal[0]}={l.direction[:3]}" for l in leans) if leans else ""
                suffix = " (cap)" if cap_hit else ""
                print(f"  {sym} (earnings {next_earnings}): {outcome}{suffix} [{leans_summary}]")

            except HTTPException as exc:
                draft_attempts += 1
                if not dry_run:
                    _log_evaluation(session, sym, "error", note=f"HTTP {exc.status_code}: {exc.detail}")
                print(f"  {sym} (earnings {next_earnings}): error -- {exc.detail}")

            except Exception as exc:
                tb = traceback.format_exc()
                draft_attempts += 1
                if not dry_run:
                    _log_evaluation(session, sym, "error", note=f"{type(exc).__name__}: {exc}")
                print(f"  {sym} (earnings {next_earnings}): error -- {exc}\n{tb}")

        if not dry_run:
            await session.commit()

        # ── Summary ───────────────────────────────────────────────────────────
        print(
            f"\n[auto-pick] Done. {new_picks} new picks, "
            f"{open_count + new_picks} total open v2, "
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
    v2_fields: dict | None = None,
) -> None:
    """Add an AlertPickEvaluation row (uncommitted -- caller commits)."""
    kwargs: dict = dict(
        symbol=symbol,
        source="nightly",
        outcome=outcome,
        leans=leans,
        alert_pick_id=pick_id,
        note=note,
    )
    if v2_fields:
        kwargs.update(v2_fields)
    session.add(AlertPickEvaluation(**kwargs))


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return asyncio.run(_run(dry_run=dry_run))


if __name__ == "__main__":
    sys.exit(main())
