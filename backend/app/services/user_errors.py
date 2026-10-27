"""No visitor ever sees a raw error (Sam, 2026-10-27: BNY's research note showed "Generation failed 'NoneType' object has no attribute
'upper'"). Every action a visitor takes answers a failure with its feature's plain sentence (PLAIN), and the real error goes to the
morning digest: record() keeps it under the New York day (KEY), the nightly's digest lists the previous day's (digest_lines).

    plain(feature)                     the visitor's sentence for a feature
    await record(feature, exc, symbol) store the real error for the digest, never raising
    digest_lines(raw)                  "feature SYM: error" lines for the digest from a stored day
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.redact import redact

NY = ZoneInfo("America/New_York")
KEY = "user_errors:{day}"
KEEP_PER_DAY = 200            # a day keeps this many errors; the digest shows the count and DIGEST_EXAMPLES of them
RETRY = "Try again in a few minutes."
PLAIN = {
    "research_note": f"Ivy couldn't write this note right now. {RETRY}",
    "research_verify": f"Ivy couldn't check this note right now. {RETRY}",
    "options_read": f"Ivy couldn't write this read right now. {RETRY}",
    "explain": f"Ivy couldn't explain this right now. {RETRY}",
    "quote": f"The price couldn't be loaded right now. {RETRY}",
    "data": f"This data couldn't be loaded right now. {RETRY}",
    "build": f"Ivy couldn't build this trade right now. {RETRY}",
    "ask_ivy": f"Ivy couldn't answer just now. {RETRY}",
    "unexpected": f"Something went wrong on our side. {RETRY}",
}


def plain(feature: str) -> str:
    return PLAIN.get(feature, PLAIN["unexpected"])


def day_key(now: datetime | None = None) -> str:
    return KEY.format(day=(now or datetime.now(timezone.utc)).astimezone(NY).date().isoformat())


async def record(feature: str, exc: BaseException | str, symbol: str | None = None) -> None:
    """Keep the real error for the digest (its own session; a failure here never reaches the visitor)."""
    try:
        from app.database import ScriptSessionLocal
        from app.services.system_metadata_service import get_value, set_value
        line = {"at": datetime.now(timezone.utc).isoformat(), "feature": feature, "symbol": symbol,
                "error": (redact(exc) if isinstance(exc, BaseException) else str(exc))[:300]}
        print(f"[user-error] {feature} {symbol or ''}: {line['error']}", flush=True)
        async with ScriptSessionLocal() as s:
            key = day_key()
            rows = json.loads(await get_value(s, key) or "[]")
            if len(rows) < KEEP_PER_DAY:
                rows.append(line)
                await set_value(s, key, json.dumps(rows))
                await s.commit()
    except Exception as e:                       # the visitor already has the plain sentence; the log keeps this
        print(f"[user-error] could not record: {redact(e)}", flush=True)


def digest_lines(raw: str | None) -> list[str]:
    """Pure: "feature SYM: error" for each stored error of a day."""
    try:
        rows = json.loads(raw or "[]")
    except ValueError:
        return []
    return [f"{r.get('feature')} {r.get('symbol') or ''}".rstrip() + f": {r.get('error')}" for r in rows if isinstance(r, dict)]
