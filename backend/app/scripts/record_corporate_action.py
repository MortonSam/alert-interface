"""Record a corporate action the P/E rule must see: a spin-off, merger, acquisition by share exchange or rename-merge, dated,
with the counterparty's name. Stored as an events row of type other with metadata {corporate_action, counterparty}; the nightly
P/E marks any window holding it "not meaningful yet" until four clean quarters exist. Dry run by default.

    python -m app.scripts.record_corporate_action FDX spin_off 2026-06-01 "FedEx Freight"
    python -m app.scripts.record_corporate_action FDX spin_off 2026-06-01 "FedEx Freight" --write
    python -m app.scripts.record_corporate_action FDX spin_off 2026-06-01 "FedEx Freight" --accession=0000... --write   # the filing as the receipt

The accession is the completion 8-K whatever item it was reported under: Chevron (Hess) and Palo Alto (CyberArk) filed theirs
under Item 8.01, Paramount's sits under its pre-merger CIK and Bunge's predates the scanner's window, so scan_corporate_actions
(Item 2.01, current CIK, 15 months) never records them and they are recorded here by hand.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.valuation import ACTION_VERBS


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    accession = next((a.split("=", 1)[1] for a in argv if a.startswith("--accession=")), None)
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 4 or args[1] not in ACTION_VERBS:
        print(__doc__); print(f"kinds: {', '.join(ACTION_VERBS)}"); return 2
    sym, kind, day, name = args[0].upper(), args[1], date.fromisoformat(args[2]), args[3]
    async with ScriptSessionLocal() as s:
        ticker = (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
        if ticker is None:
            print(f"no ticker {sym}"); return 2
        existing = (await s.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.OTHER, Event.event_date == day))).scalars().all()
        dup = [e for e in existing if (e.metadata_ or {}).get("corporate_action") == kind]
        print(f"{sym}: {kind} on {day} with {name}" + (" (already recorded)" if dup else "") + ("" if write else "; dry run, nothing written"))
        if write and not dup:
            s.add(Event(ticker_id=ticker.id, event_type=EventType.OTHER, event_date=day, title=f"{sym} {kind.replace('_', ' ')}: {name}", source=DataSource.MANUAL,
                        is_confirmed=True, confirmation_note=(f"8-K {accession}" if accession else "recorded by record_corporate_action"),
                        metadata_={"corporate_action": kind, "counterparty": name, **({"accession": accession} if accession else {})}))
            await s.commit()
            print("  recorded; the next nightly P/E run applies it")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
