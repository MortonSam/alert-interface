"""Per-dataset ages from the step outcomes, and the run's status: what /health and the freshness lines read.

The global last_refreshed_at used to be written whatever the steps did. Now each dataset's age is the oldest last
success among the steps that produce it, and its ok flag is whether every one of those steps exited 0 on its latest
run. The courier's chains count as a dataset through the "Courier ingest" outcome the ingest route records.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

COURIER_STEP_LABEL = "Courier ingest"
COURIER_RUN_GAP_HOURS = 3        # ingest calls this close together are one courier run
COURIER_RAN_WITHIN_HOURS = 20    # the digest calls the courier "ran" when its last ingest is this recent

DATASETS: dict[str, tuple[str, ...]] = {
    "prices":            ("Price bars shadow (Intrinio)",),
    "chains":            (COURIER_STEP_LABEL,),
    "reactions":         ("Historical reactions (--all)", "Missed reports (catch_up_reports)"),
    "analyst":           ("Analyst actions", "Analyst reaction stats", "Analyst recommendations (Finnhub)"),
    "iv":                ("IV + RV snapshot (snapshot_iv)",),
    "rv":                ("RV rank precompute",),
    "earnings_calendar": ("Refresh earnings calendar (Finnhub)", "EPS actuals (Finnhub)"),
}

# the chains dataset follows the source the pages read (settings.options_primary_source): the courier's ingest, or Intrinio's step
CHAIN_STEPS: dict[str, tuple[str, ...]] = {"courier": (COURIER_STEP_LABEL,), "intrinio": ("Options chains (Intrinio)",)}


def datasets_for(primary: str | None) -> dict[str, tuple[str, ...]]:
    """DATASETS with the chains dataset read from the primary options source's step."""
    return {**DATASETS, "chains": CHAIN_STEPS.get(primary or "courier", DATASETS["chains"])}


DATASET_LABELS = {"prices": "Prices", "chains": "Options data", "reactions": "Earnings history", "analyst": "Analyst data",
                  "iv": "Implied volatility", "rv": "Realized volatility", "earnings_calendar": "Earnings calendar"}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def dataset_ages(step_outcomes: dict, last_success: dict[str, str | None], primary: str | None = None) -> dict[str, dict]:
    """{dataset: {at, ok, failed, steps}}. `at` is the oldest last-success stamp among the dataset's steps (None when
    any step has never succeeded); `failed` names the steps whose latest outcome did not exit 0. The chains dataset reads
    the primary options source's step (settings.options_primary_source unless `primary` is given)."""
    if primary is None:
        from app.config import settings
        primary = settings.options_primary_source
    out = {}
    for name, steps in datasets_for(primary).items():
        stamps = [_parse(last_success.get(s)) for s in steps]
        failed = [s for s in steps if (step_outcomes.get(s) or {}).get("exit") not in (0,)]
        at = min(stamps) if stamps and all(stamps) else None
        out[name] = {"at": at.isoformat() if at else None, "ok": not failed, "failed": failed, "steps": list(steps)}
    return out


def run_status(step_outcomes: dict, step_labels: list[str]) -> tuple[str, list[str]]:
    """("ok" | "degraded", failed step labels): degraded when any current step's latest outcome failed or timed out."""
    failed = [label for label in step_labels if label in step_outcomes and step_outcomes[label].get("exit") not in (0, None)]
    return ("degraded" if failed else "ok"), failed


def courier_run_fields(prev: dict | None, now: datetime, tickers: int, chains: int, failures: list[str], captured_at: str | None) -> dict:
    """The "Courier ingest" outcome after one ingest call: counts accumulate within a run (calls within
    COURIER_RUN_GAP_HOURS of the last), and start over for a new run."""
    prev = prev or {}
    last = _parse(prev.get("at"))
    same_run = last is not None and now - last <= timedelta(hours=COURIER_RUN_GAP_HOURS)
    t = (prev.get("tickers", 0) if same_run else 0) + tickers
    c = (prev.get("chains", 0) if same_run else 0) + chains
    f = ((prev.get("failures_detail") or []) if same_run else []) + failures
    started = prev.get("run_started_at") if same_run and prev.get("run_started_at") else now.isoformat()
    return {"exit": 0 if not f else 1, "at": now.isoformat(), "run_started_at": started, "tickers": t, "chains": c, "failures": len(f),
            "failures_detail": f[:50], "captured_at": captured_at or prev.get("captured_at") if same_run else captured_at}


def courier_summary(step_outcomes: dict, now: datetime) -> dict:
    """What the digest says about the courier: ran within COURIER_RAN_WITHIN_HOURS, when (New York clock), tickers, failures."""
    o = step_outcomes.get(COURIER_STEP_LABEL) or {}
    at = _parse(o.get("at"))
    ran = at is not None and now - at <= timedelta(hours=COURIER_RAN_WITHIN_HOURS)
    at_local = None
    if at is not None:
        from zoneinfo import ZoneInfo
        at_local = at.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M ET")
    return {"ran": ran, "at": o.get("at"), "at_local": at_local, "tickers": o.get("tickers", 0), "failures": o.get("failures", 0)}
