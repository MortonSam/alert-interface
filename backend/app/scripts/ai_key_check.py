"""Nightly AI key check: one tiny call (ai_health.CHECK_MODEL, a few tokens) with the key production uses, so a dead key or an
empty credit balance is found before a visitor is. The result goes to system_metadata (ai_health.CHECK_KEY); a failure is also
recorded as a failed call (ai_health.record_failure) and exits 1, so the step, validate and /health all show it.

Usage: python -m app.scripts.ai_key_check
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from app.services import ai_health as H


async def run() -> int:
    from anthropic import AsyncAnthropic
    from app.config import settings
    from app.database import ScriptSessionLocal
    from app.services.system_metadata_service import set_value
    from app.services.prod_key_guard import check_production_key
    check_production_key()              # production's key check only with production's key (services/prod_key_guard)
    result = {"at": datetime.now(timezone.utc).isoformat(), "model": H.CHECK_MODEL, "ok": False, "status": None, "error": None}
    try:
        msg = await AsyncAnthropic(api_key=settings.anthropic_api_key).messages.create(
            model=H.CHECK_MODEL, max_tokens=5, messages=[{"role": "user", "content": "ping"}])
        result.update(ok=True, status=200, tokens=msg.usage.input_tokens + msg.usage.output_tokens)
    except Exception as exc:
        entry = await H.record_failure("key_check", exc)
        result.update(status=entry["status"], error=f"{entry['kind']}: {entry['message']}")
    async with ScriptSessionLocal() as s:
        await set_value(s, H.CHECK_KEY, json.dumps(result))
        await s.commit()
    print(f"AI key check: {'ok' if result['ok'] else 'FAILED ' + str(result['error'])}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
