"""Nightly AI key check: one tiny call (ai_health.CHECK_MODEL, a few tokens) with the key production uses, so a dead key or an
empty credit balance is found before a visitor is. The result goes to system_metadata (ai_health.CHECK_KEY); a failure is also
recorded as a failed call (ai_health.record_failure) and exits 1, so the step, validate and /health all show it. A failure for
credit or billing instead pauses the night's AI (services/ai_pause) and exits 0; the next check that passes clears the pause.

Usage: python -m app.scripts.ai_key_check
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from app.services import ai_health as H
from app.services import ai_pause as P


async def run() -> int:
    from anthropic import AsyncAnthropic
    from app.config import settings
    from app.database import ScriptSessionLocal
    from app.services.system_metadata_service import get_value, set_value
    from app.services.prod_key_guard import check_production_key
    check_production_key()              # production's key check only with production's key (services/prod_key_guard)
    result = {"at": datetime.now(timezone.utc).isoformat(), "model": H.CHECK_MODEL, "ok": False, "status": None, "error": None}
    try:
        msg = await AsyncAnthropic(api_key=settings.anthropic_api_key).messages.create(
            model=H.CHECK_MODEL, max_tokens=5, messages=[{"role": "user", "content": "ping"}])
        result.update(ok=True, status=200, tokens=msg.usage.input_tokens + msg.usage.output_tokens)
    except Exception as exc:
        # a credit or billing failure pauses the night's AI (services/ai_pause), whose own alert is the one sent
        entry = await H.record_failure("key_check", exc, alarm=H.classify(exc) not in P.PAUSE_KINDS)
        result.update(status=entry["status"], error=f"{entry['kind']}: {entry['message']}", kind=entry["kind"])
    async with ScriptSessionLocal() as s:
        await set_value(s, H.CHECK_KEY, json.dumps(result))
        prior = P.parse(await get_value(s, P.PAUSE_KEY))
        if result["ok"]:
            if prior:
                await set_value(s, P.PAUSE_KEY, "")
                await s.commit()
                from app.services.notify import notify
                await notify("AI resumed", f"The key check passed; the AI paused since {prior['since'][:10]} runs again tonight.")
        elif result.get("kind") in P.PAUSE_KINDS:
            await set_value(s, P.PAUSE_KEY, json.dumps(P.started(prior, result["kind"], datetime.now(timezone.utc))))
        await s.commit()
    if not result["ok"] and result.get("kind") in P.PAUSE_KINDS:
        print(f"AI key check: {result['error']}; the night's AI steps are paused (services/ai_pause)")
        return 0                     # the check did its job: a pause, not a failed step
    print(f"AI key check: {'ok' if result['ok'] else 'FAILED ' + str(result['error'])}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
