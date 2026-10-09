#!/usr/bin/env bash
# Chain courier wrapper for launchd (installed at ~/.alert-interface/run_courier.sh; the repo copy is backend/ops/courier/run_courier.sh).
# launchd fires this every 5 minutes on weekdays between 13:00 and 19:00 local; app.scripts.courier_gate starts the run only on a New
# York trading day between 16:05 and 16:45 New York, once per New York day, whatever the Mac's time zone. Reads ADMIN_TOKEN from
# courier.env, runs the courier, logs output. Skips cleanly if the project or Python is missing.

set -uo pipefail

DIR="$HOME/.alert-interface"
LOG="$DIR/courier.log"
ENV_FILE="$DIR/courier.env"
STATE="$DIR/courier_last_run"         # the New York date the last run started
LOCK="$DIR/courier.lock"
PROJECT="$HOME/projects/alert-interface/backend"
BASE_URL="https://alert-interface-production.up.railway.app"
PYTHON="$(command -v python3 || true)"
[[ -z "$PYTHON" || ! -d "$PROJECT" ]] && exit 0
cd "$PROJECT"

# ── Gate: quiet unless it is time (no log line for the other 70-odd fires a day) ──────────────────────────────────────────────
GATE_NOW=()
[[ -n "${COURIER_NOW:-}" ]] && GATE_NOW=(--now "$COURIER_NOW")      # tests simulate a clock
"$PYTHON" -m app.scripts.courier_gate check --state "$STATE" "${GATE_NOW[@]}" > /dev/null || exit 0
[[ -d "$LOCK" ]] && find "$LOCK" -maxdepth 0 -mmin +120 -exec rmdir {} \; 2>/dev/null   # a lock left by a crash two hours ago is stale
mkdir "$LOCK" 2>/dev/null || exit 0                                   # a run is already going
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
"$PYTHON" -m app.scripts.courier_gate mark --state "$STATE" "${GATE_NOW[@]}"

exec >> "$LOG" 2>&1
echo ""
echo "═══ $(date '+%Y-%m-%d %H:%M:%S %Z') / $(TZ=America/New_York date '+%H:%M:%S %Z') ═══"

if [[ -n "${COURIER_DRY_RUN:-}" ]]; then
    echo "DRY RUN: would start the courier now"
    exit 0
fi

# ── Guards: env file and token ───────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    echo "SKIP: $ENV_FILE not found"; "$PYTHON" -m app.scripts.courier_gate clear --state "$STATE"; exit 0
fi
source "$ENV_FILE"
if [[ -z "${ADMIN_TOKEN:-}" || "$ADMIN_TOKEN" == "PASTE_YOUR_TOKEN_HERE" ]]; then
    echo "SKIP: ADMIN_TOKEN not set in courier.env"; "$PYTHON" -m app.scripts.courier_gate clear --state "$STATE"; exit 0
fi
export ADMIN_TOKEN
if ! "$PYTHON" -c "import httpx, yfinance" 2>/dev/null; then
    echo "SKIP: httpx or yfinance not importable"; "$PYTHON" -m app.scripts.courier_gate clear --state "$STATE"; exit 0
fi

# ── Run ──────────────────────────────────────────────────────────────────────
OUT="$DIR/courier_last_output.txt"
"$PYTHON" -m app.scripts.chain_courier --base-url "$BASE_URL" 2>&1 | tee "$OUT"
rc=${PIPESTATUS[0]}
echo "Done (exit $rc)"
# production unreachable before anything was pushed (2026-10-07: a DNS failure at 16:11): the day may retry at the next fire
if grep -q "Nothing pushed" "$OUT"; then
    "$PYTHON" -m app.scripts.courier_gate clear --state "$STATE"
    echo "Nothing was pushed: the next fire before 16:45 New York retries"
fi
