"""One way to tell a person: ntfy. Settings NTFY_TOPIC and NTFY_SERVER; an empty topic sends nothing and returns False
(validate's alerting_configured check WARNs about it, so silence is never mistaken for health).

Message formats (title / body), all plain text:
  Step failure   "Nightly step failed: {label}"      / "exit {code} after {seconds}s" or "timed out after {seconds}s", then the stderr tail
  Validate error "Validate ERROR: {check}"           / the check's message, then up to 3 of its rows
  Courier        "Courier did not run"               / sent inside the digest, not on its own
  Digest         "Nightly {date}: {passed}/{total} steps passed" /
                 "failed: a, b | validate: E errors, W warnings | chain coverage P% | courier ran 16:07 ET, 421 tickers (91 failed)"
"""
from __future__ import annotations

import httpx

from app.config import settings

TIMEOUT_SECONDS = 10
PRIORITY_HIGH = "high"
PRIORITY_DEFAULT = "default"


def configured() -> bool:
    return bool((settings.ntfy_topic or "").strip())


def _url() -> str:
    return f"{(settings.ntfy_server or 'https://ntfy.sh').rstrip('/')}/{settings.ntfy_topic.strip()}"


def _headers(title: str, priority: str, tags: tuple[str, ...]) -> dict[str, str]:
    h = {"Title": title, "Priority": priority}
    if tags:
        h["Tags"] = ",".join(tags)
    return h


def notify_sync(title: str, message: str, priority: str = PRIORITY_DEFAULT, tags: tuple[str, ...] = ()) -> bool:
    """Send one message; True when sent. Never raises: a failed alert must not fail the step that raised it."""
    if not configured():
        return False
    try:
        httpx.post(_url(), content=message.encode("utf-8"), headers=_headers(title, priority, tags), timeout=TIMEOUT_SECONDS).raise_for_status()
        return True
    except Exception as exc:
        print(f"  [WARN] ntfy send failed: {exc}", flush=True)
        return False


async def notify(title: str, message: str, priority: str = PRIORITY_DEFAULT, tags: tuple[str, ...] = ()) -> bool:
    if not configured():
        return False
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            (await client.post(_url(), content=message.encode("utf-8"), headers=_headers(title, priority, tags))).raise_for_status()
        return True
    except Exception as exc:
        print(f"  [WARN] ntfy send failed: {exc}", flush=True)
        return False


# ── the messages, built in one place so tests can pin them ───────────────────

def step_failure_message(label: str, exit_code: int, seconds: float, stderr_tail: str | None) -> tuple[str, str]:
    how = f"timed out after {seconds:.0f}s" if exit_code == -1 else f"exit {exit_code} after {seconds:.0f}s"
    return f"Nightly step failed: {label}", how + (f"\n{stderr_tail}" if stderr_tail else "")


def validate_error_message(check: str, message: str, rows: list[str]) -> tuple[str, str]:
    body = message + "".join(f"\n· {r}" for r in rows[:3])
    return f"Validate ERROR: {check}", body


def digest_message(run_date: str, passed: int, total: int, failed: list[str], validate: dict | None, chain_coverage_pct: float | None,
                   courier: dict | None) -> tuple[str, str]:
    parts = [f"failed: {', '.join(failed)}" if failed else "all steps passed"]
    if validate:
        parts.append(f"validate: {validate.get('error_count', 0)} errors, {validate.get('warn_count', 0)} warnings")
    parts.append(f"chain coverage {chain_coverage_pct:.0f}%" if chain_coverage_pct is not None else "chain coverage unknown")
    if courier and courier.get("ran"):
        parts.append(f"courier ran {courier.get('at_local', '?')}, {courier.get('tickers', 0)} tickers ({courier.get('failures', 0)} failed)")
    else:
        parts.append("courier did not run")
    return f"Nightly {run_date}: {passed}/{total} steps passed", " | ".join(parts)
