"""A nightly step's own account of what it did, kept where /health reads it.

refresh.py records exit, seconds, at and the stderr excerpt for every step and
merges over whatever the step itself wrote under its label, so a step can add
the fields that explain a failure (validate: which checks; FOMC: which tickers
stalled) and they survive.
"""
from __future__ import annotations

import json

from app.database import ScriptSessionLocal
from app.services.system_metadata_service import get_value, set_value


def merged_outcomes(raw: str | None, label: str, fields: dict) -> dict:
    """Pure: the step_outcomes blob with `fields` merged into `label`'s entry."""
    try:
        outcomes = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        outcomes = {}
    entry = dict(outcomes.get(label) or {})
    entry.update(fields)
    outcomes[label] = entry
    return outcomes


async def record_step_fields(label: str, fields: dict) -> None:
    """Merge `fields` into step_outcomes[label]. Never raises: a diagnosis must not fail the step."""
    try:
        async with ScriptSessionLocal() as session:
            raw = await get_value(session, "step_outcomes")
            await set_value(session, "step_outcomes", json.dumps(merged_outcomes(raw, label, fields)))
            await session.commit()
    except Exception as exc:
        print(f"  [WARN] could not record step outcome for {label}: {exc}", flush=True)
