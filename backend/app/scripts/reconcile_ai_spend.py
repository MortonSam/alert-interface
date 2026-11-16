"""Nightly: the spend ledger against Anthropic's own record for the production key (Sam, 2026-11-16). No model call.

On Nov 10 to 14 the console showed $19.91 on the production key while the ledger (services/ai_spend) recorded $3.11 and the daily
cap never tripped: the ledger can only count calls made through this codebase's gateway (services/anthropic_client). This step reads
the previous New York day's tokens for the production key from Anthropic's usage report (services/ai_usage_report, Admin API, needs
ANTHROPIC_ADMIN_KEY), prices them with the ledger's own table, and when Anthropic's figure exceeds the ledger's by more than
MISMATCH_FLOOR_USD and MISMATCH_SHARE of it, alerts Sam's phone (services/notify) and leaves an ERROR for validate
(check_ai_spend_reconciled). The result is kept as system_metadata "ai_reconcile:{day}" and RECONCILE_KEY.

Usage: python -m app.scripts.reconcile_ai_spend [--day=YYYY-MM-DD]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, time, timedelta, timezone

from app.services.ai_spend import CLOCK

STEP_LABEL = "AI spend reconciliation"
RECONCILE_KEY = "ai_reconcile_latest"
MISMATCH_FLOOR_USD = 0.25          # Anthropic above the ledger by more than this and
MISMATCH_SHARE = 0.15              # by more than this share of Anthropic's figure is a mismatch


def window(day: date) -> tuple[datetime, datetime]:
    """Pure: the New York day as UTC instants (midnight to midnight; both on the hour)."""
    start = datetime.combine(day, time(0), tzinfo=CLOCK)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def judge(anthropic_usd: float, ledger_usd: float) -> bool:
    """Pure: True when Anthropic's figure exceeds the ledger's by more than the floor and the share (the ledger counts timed-out
    attempts at their ceiling, so it may sit above Anthropic's; that is never a mismatch)."""
    gap = anthropic_usd - ledger_usd
    return gap > MISMATCH_FLOOR_USD and gap > MISMATCH_SHARE * anthropic_usd


def message(day: str, anthropic_usd: float, ledger_usd: float, by_model: dict) -> tuple[str, str]:
    """Pure: the phone alert."""
    models = ", ".join(f"{m} {t.get('in', 0) + t.get('cache_write', 0) + t.get('cache_read', 0):,} in / {t.get('out', 0):,} out"
                       for m, t in sorted(by_model.items()))
    return ("AI spend not in the ledger",
            f"{day} (New York): Anthropic shows ${anthropic_usd:.2f} on the production key, the site's ledger ${ledger_usd:.2f}. "
            f"Something used the key outside the site's gateway, or a call went unrecorded. Anthropic's tokens: {models}. "
            "If the key may have leaked, rotate it in the console and on Railway.")


async def run(day: date) -> dict:
    from app.config import settings
    from app.database import ScriptSessionLocal
    from app.services import ai_spend
    from app.services import ai_usage_report as U
    from app.services.system_metadata_service import get_value, set_value
    key = day.isoformat()
    async with ScriptSessionLocal() as s:
        ledger_usd = round(float(await get_value(s, f"{ai_spend.SPEND_KEY}:{key}") or 0), 4)
        ledger_tokens = await ai_spend.tokens_by_model(s, key)
    result = {"day": key, "at": datetime.now(timezone.utc).isoformat(), "ledger_usd": ledger_usd, "ledger_tokens": ledger_tokens,
              "configured": bool(settings.anthropic_admin_key)}
    if settings.anthropic_admin_key:
        try:
            start, end = window(day)
            key_id = await U.production_key_id(settings.anthropic_admin_key, settings.anthropic_api_key)
            tokens = await U.key_tokens(settings.anthropic_admin_key, key_id, start, end)
            anthropic_usd, unpriced = U.priced(tokens)
            result.update(anthropic_usd=anthropic_usd, anthropic_tokens=tokens, unpriced_models=unpriced,
                          mismatch=judge(anthropic_usd, ledger_usd) or bool(unpriced))
        except Exception as exc:
            from app.services.redact import redact
            result.update(error=redact(exc)[:200])
    async with ScriptSessionLocal() as s:
        await set_value(s, f"ai_reconcile:{key}", json.dumps(result))
        await set_value(s, RECONCILE_KEY, json.dumps(result))
        await s.commit()
    from app.services.notify import PRIORITY_HIGH, notify
    if result.get("mismatch"):
        title, body = message(key, result["anthropic_usd"], ledger_usd, result["anthropic_tokens"])
        await notify(title, body, priority=PRIORITY_HIGH, tags=("warning",))
    elif result.get("error"):
        await notify("AI spend could not be reconciled", f"{key}: Anthropic's usage report could not be read ({result['error']}).")
    from app.services.step_outcomes import record_step_fields
    await record_step_fields(STEP_LABEL, {k: v for k, v in result.items() if k not in ("ledger_tokens", "anthropic_tokens")})
    return result


def main(argv: list[str]) -> int:
    arg = next((a.split("=", 1)[1] for a in argv if a.startswith("--day=")), None)
    day = date.fromisoformat(arg) if arg else datetime.now(CLOCK).date() - timedelta(days=1)
    r = asyncio.run(run(day))
    print(json.dumps({k: v for k, v in r.items() if k != "ledger_tokens"}, default=str))
    return 0                         # a mismatch alerts on its own and is validate's ERROR; the night carries on


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
