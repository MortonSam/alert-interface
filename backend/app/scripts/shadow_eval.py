"""Nightly shadow model evaluation.

For the SAME candidate set auto_pick evaluates (earnings in 1-5 trading
days), train the shadow model on all events before today, predict each
candidate, and insert one row per candidate into shadow_picks.

Never writes to alert_picks.

Usage:
    python -m app.scripts.shadow_eval
    python -m app.scripts.shadow_eval --dry-run
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sqlalchemy import text as sa_text

from app.database import ScriptSessionLocal
from app.models.alert_pick import AlertPick, AlertPickEvaluation
from app.models.earnings_feature import EarningsFeature
from app.models.enums import EventType
from app.models.event import Event
from app.models.ivy_train_log import IvyTrainLog
from app.models.shadow_pick import ShadowPick
from app.models.ticker import Ticker
from app.services.ivy_shadow import train, predict, FEATURE_COLS
from app.services.ivy_v2 import compute_live_features, decide as v2_decide, MIN_PRIOR_N, MOMENTUM_CUTOFF
from app.services.system_metadata_service import get_value, set_value

SHADOW_THRESHOLD = 0.58  # default threshold for would_pick


async def _run(dry_run: bool = False) -> int:
    today = date.today()
    horizon = today + timedelta(days=7)

    async with ScriptSessionLocal() as session:
        # Same candidate query as auto_pick
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
            print("[shadow] No candidates with earnings in next 1-5 trading days.")
            return 0

        print(f"[shadow] {len(candidates)} candidates, dry_run={dry_run}")

        # Load all features for training
        all_result = await session.execute(
            select(EarningsFeature).order_by(EarningsFeature.event_date)
        )
        all_features = all_result.scalars().all()

        if len(all_features) < 50:
            print(f"[shadow] Insufficient features ({len(all_features)}), skipping.")
            return 0

        # Train on all events before today
        try:
            tr = train(all_features, cutoff_date=today)
        except ValueError as e:
            print(f"[shadow] Training failed: {e}")
            return 1

        model = tr.model
        positive_rate = tr.n_positive / tr.n_train
        print(f"[shadow] Trained on {tr.n_train} rows, {tr.n_positive} positive "
              f"({positive_rate*100:.1f}%)")
        if tr.holdout_accuracy is not None:
            print(f"[shadow] Holdout accuracy: {tr.holdout_accuracy*100:.1f}% "
                  f"(n={tr.holdout_n})")

        # Query the current reaction computation version
        comp_version = (await session.execute(
            sa_text(
                "SELECT COALESCE(MAX(computation_version), 1) "
                "FROM historical_reactions WHERE event_type = 'earnings'"
            )
        )).scalar()

        # Persist model artifact
        if not dry_run:
            artifact = {
                "model_b64": model.serialize(),
                "train_cutoff": today.isoformat(),
                "n_train": tr.n_train,
                "n_positive": tr.n_positive,
                "feature_importance": tr.feature_importance,
                "threshold": SHADOW_THRESHOLD,
            }
            await set_value(session, "shadow_model_latest", json.dumps(artifact))

            # Persist training metrics
            session.add(IvyTrainLog(
                n_rows=tr.n_train,
                positive_rate=round(positive_rate, 4),
                holdout_accuracy=round(tr.holdout_accuracy, 4) if tr.holdout_accuracy is not None else None,
                holdout_positive_rate=round(tr.holdout_positive_rate, 4) if tr.holdout_positive_rate is not None else None,
                holdout_n=tr.holdout_n,
                computation_version=comp_version,
            ))

            # Write accuracy to step_outcomes so /health shows it
            raw = await get_value(session, "step_outcomes")
            outcomes = json.loads(raw) if raw else {}
            shadow_entry = outcomes.get("Shadow eval", {})
            shadow_entry["holdout_accuracy"] = round(tr.holdout_accuracy, 4) if tr.holdout_accuracy is not None else None
            shadow_entry["holdout_positive_rate"] = round(tr.holdout_positive_rate, 4) if tr.holdout_positive_rate is not None else None
            shadow_entry["holdout_n"] = tr.holdout_n
            shadow_entry["n_train"] = tr.n_train
            shadow_entry["computation_version"] = comp_version
            outcomes["Shadow eval"] = shadow_entry
            await set_value(session, "step_outcomes", json.dumps(outcomes))

        # Evaluate each candidate
        inserted = 0
        for row in candidates:
            sym = row.symbol
            next_earnings = row.next_earnings

            # Get live features for this candidate
            live = await compute_live_features(sym, session)
            if live is None:
                print(f"  {sym} (earnings {next_earnings}): no live features")
                continue

            # Shadow prediction
            pred = predict(model, live)

            # v2 decision (for comparison logging)
            v2_result = await v2_decide(
                features=live,
                db=session,
                symbol=sym,
                event_date=live.event_date,
                all_features=all_features,
                ai_client=None,
            )

            # Find v2 pick_id if v2 picked this symbol tonight
            v2_pick_id = None
            if v2_result.pick:
                pick_row = (await session.execute(
                    select(AlertPick.id)
                    .where(
                        AlertPick.symbol == sym,
                        AlertPick.status == "open",
                        AlertPick.source != "visitor",
                    )
                    .order_by(AlertPick.generated_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
                v2_pick_id = pick_row

            would_pick = pred.probability_up_5d >= SHADOW_THRESHOLD
            v2_decision = v2_result.skip_reason or ("picked" if v2_result.pick else "skipped")

            print(f"  {sym} (earnings {next_earnings}): "
                  f"prob={pred.probability_up_5d:.3f} "
                  f"would_pick={would_pick} "
                  f"v2={v2_decision} "
                  f"factors={pred.top_factors[:2]}")

            if not dry_run:
                values = dict(
                    symbol=sym,
                    event_date=next_earnings,
                    eval_date=today,
                    probability=Decimal(str(pred.probability_up_5d)),
                    threshold_used=Decimal(str(SHADOW_THRESHOLD)),
                    would_pick=would_pick,
                    top_factors=pred.top_factors,
                    v2_decision=v2_decision,
                    v2_pick_id=v2_pick_id,
                )
                stmt = (
                    pg_insert(ShadowPick)
                    .values(**values)
                    .on_conflict_do_update(
                        constraint="uq_shadow_picks_symbol_event_eval",
                        set_={
                            "probability": values["probability"],
                            "threshold_used": values["threshold_used"],
                            "would_pick": values["would_pick"],
                            "top_factors": values["top_factors"],
                            "v2_decision": values["v2_decision"],
                            "v2_pick_id": values["v2_pick_id"],
                            "decided_at": func.now(),
                        },
                    )
                )
                await session.execute(stmt)
                inserted += 1

        if not dry_run:
            await session.commit()

        print(f"\n[shadow] Done. {inserted} shadow picks upserted.")
    return 0


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return asyncio.run(_run(dry_run=dry_run))


if __name__ == "__main__":
    sys.exit(main())
