"""Dry-run the v2 engine on a handful of tickers.

Loads or computes features, calls decide(), prints the full receipt.
Validates the engine works end-to-end with DB data.

CLI
---
    python -m app.scripts.dry_run_v2
"""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature
from app.services.ivy_v2 import decide, MIN_PRIOR_N, MOMENTUM_CUTOFF


async def main() -> None:
    async with ScriptSessionLocal() as session:
        # Load all features (needed for walk-forward base rate)
        all_result = await session.execute(
            select(EarningsFeature).order_by(EarningsFeature.event_date)
        )
        all_features = all_result.scalars().all()

        print(f"Loaded {len(all_features)} total earnings features\n")

        # Pick 5 recent events that have actual_5d (for validation) and span
        # different gate outcomes: some should pass, some should fail
        # Strategy: get recent events with momentum data, mix of strong neg and mild
        candidates = []
        for f in reversed(all_features):
            if f.actual_5d is not None and f.momentum_20d is not None:
                candidates.append(f)
            if len(candidates) >= 50:
                break

        # Select up to 5: try to get a mix of qualifying and non-qualifying
        selected = []
        got_qualifier = 0
        got_non_qualifier = 0
        for f in candidates:
            mom = float(f.momentum_20d)
            prior_n = int(f.prior_n) if f.prior_n is not None else 0
            qualifies = mom <= MOMENTUM_CUTOFF * 100 and prior_n >= MIN_PRIOR_N

            if qualifies and got_qualifier < 3:
                selected.append(f)
                got_qualifier += 1
            elif not qualifies and got_non_qualifier < 2:
                selected.append(f)
                got_non_qualifier += 1

            if len(selected) >= 5:
                break

        # If we didn't get enough, fill from whatever's left
        if len(selected) < 5:
            for f in candidates:
                if f not in selected:
                    selected.append(f)
                if len(selected) >= 5:
                    break

        print(f"Selected {len(selected)} tickers for dry run\n")
        print("=" * 90)

        for feat in selected:
            symbol = feat.symbol
            event_date = feat.event_date

            print(f"\n{'─' * 90}")
            print(f"  {symbol}  event_date={event_date}")
            mom_val = float(feat.momentum_20d) if feat.momentum_20d is not None else None
            avg5d_val = float(feat.prior_avg_abs_5d) if feat.prior_avg_abs_5d is not None else None
            act5d_val = float(feat.actual_5d) if feat.actual_5d is not None else None
            print(f"  momentum_20d={f'{mom_val:.1f}%' if mom_val is not None else 'n/a'}  "
                  f"prior_n={feat.prior_n}  "
                  f"prior_avg_abs_5d={f'{avg5d_val:.2f}%' if avg5d_val is not None else 'n/a'}  "
                  f"actual_5d={f'{act5d_val:+.2f}%' if act5d_val is not None else 'n/a'}")

            result = await decide(
                features=feat,
                db=session,
                symbol=symbol,
                event_date=event_date,
                all_features=all_features,
                ai_client=None,  # template fallback only for dry run
            )

            print(f"  pick={result.pick}  direction={result.direction}  "
                  f"gate_passed={result.gate_passed}")
            if result.skip_reason:
                print(f"  skip_reason: {result.skip_reason}")
            print(f"  expected_move={result.expected_move}  implied_move={result.implied_move}")
            print(f"  Receipt:")
            for k, v in result.receipt.items():
                print(f"    {k}: {v}")

            # Verify against actual outcome
            if feat.actual_5d is not None:
                actual = float(feat.actual_5d)
                if result.pick:
                    hit = actual > 0
                    print(f"  OUTCOME: actual_5d={actual:+.2f}% → {'HIT' if hit else 'MISS'}")
                else:
                    print(f"  OUTCOME: (skipped) actual_5d={actual:+.2f}%")

        print(f"\n{'=' * 90}")
        print("Dry run complete.")


if __name__ == "__main__":
    asyncio.run(main())
