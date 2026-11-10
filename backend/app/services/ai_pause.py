"""The nightly's AI pause (Sam, 2026-11-10): when the nightly key check fails for credit or billing, every AI step that night is
skipped cleanly instead of failing call by call (Nov 5 to 10, 2026: an empty credit balance failed every note, read and reader).

- scripts/ai_key_check records the pause under PAUSE_KEY ({since, kind, alerted_on}) and exits 0: the check did its job.
- services/ai_spend.check_nightly refuses every nightly-pool model call while paused (NightlyBudgetReached), so a step that also
  does work without the model (the release reader's pattern parser, the date reader's press releases) does that work and sends
  nothing to the API.
- scripts/refresh skips AI_ONLY_STEPS outright, records them as skipped (never failed), names the pause in the morning digest, and
  sends one phone alert (ntfy, high) the first night and a reminder each night after, until a key check passes and clears it.
- validate's ai_api check is a WARN while paused (the pause is known and alerted), and step_age leaves the skipped steps out.
"""
from __future__ import annotations

import json
from datetime import date, datetime

PAUSE_KEY = "ai_paused"              # system_metadata: {"since": iso, "kind": "billing", "alerted_on": "YYYY-MM-DD" | None}
PAUSE_KINDS = ("billing",)           # an invalid key ("auth") is a real failure, never a pause
AI_ONLY_STEPS = ("Research notes (nightly)", "Research note check", "Ivy walkthroughs")


def parse(raw: str | None) -> dict | None:
    """Pure: the stored pause, or None."""
    try:
        v = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) and v.get("since") else None


def started(prior: dict | None, kind: str, now: datetime) -> dict:
    """Pure: the pause after tonight's failed check: an existing pause keeps its start and its alert record."""
    return prior if prior else {"since": now.isoformat(), "kind": kind, "alerted_on": None}


def since_words(pause: dict) -> str:
    """Pure: the pause's start as the site writes a date ("Nov 5")."""
    return datetime.fromisoformat(pause["since"]).strftime("%b %-d")


def nights(pause: dict, today: date) -> int:
    """Pure: nights paused, tonight included."""
    return (today - datetime.fromisoformat(pause["since"]).date()).days + 1


def alert_for(pause: dict, today: date, skipped_steps: list[str]) -> tuple[str, str, bool] | None:
    """Pure: (title, body, high priority) for tonight's phone alert, or None when one was sent today. The first night is high
    priority; every later night is a reminder."""
    if pause.get("alerted_on") == today.isoformat():
        return None
    n = nights(pause, today)
    skipped = ", ".join(skipped_steps) or "none"
    if n <= 1 and not pause.get("alerted_on"):
        return ("AI paused: Anthropic credit is out",
                f"The nightly key check failed for {pause.get('kind', 'billing')}. Tonight's AI steps are skipped ({skipped}) and no model call "
                "is sent; nothing is marked failed and every served note stays. Add credit; the next key check that passes resumes them.", True)
    since = datetime.fromisoformat(pause["since"]).date()
    return ("Reminder: AI still paused",
            f"Night {n} without AI (since {since.strftime('%b %-d')}): {skipped} skipped again. Add Anthropic credit to resume.", False)


def digest_line(pause: dict | None, today: date, skipped_steps: list[str]) -> str:
    """Pure: the morning digest's line while paused, or ""."""
    if not pause:
        return ""
    since = datetime.fromisoformat(pause["since"]).date()
    return (f" | AI paused since {since.strftime('%b %-d')} (night {nights(pause, today)}, {pause.get('kind', 'billing')}): skipped "
            f"{', '.join(skipped_steps) or 'none'}; no model calls sent, nothing marked failed")


async def paused(db) -> dict | None:
    from app.services.system_metadata_service import get_value
    return parse(await get_value(db, PAUSE_KEY))
