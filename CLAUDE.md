# Project Rules

## Frontend Dev Server

**Never run `npx next build` while the dev server (`next dev`) is running.** Both share the `.next` directory, and a concurrent build corrupts the dev server's webpack chunks, causing runtime TypeErrors. To validate:

- Use the dev server's own compile output (watch for "Compiled successfully" or errors in the terminal).
- If a production build is needed, stop the dev server first (`kill` the port 3000 process), then build, then restart.

## Frontend Build Check

**Every commit that touches `frontend/` runs `npm run build` in `frontend/` first**, with the dev server stopped before it and restarted after it (the two share `.next`; see above). If `next build` exits non-zero, the commit does not happen until it exits 0. Type errors only surface in the production build, and a bad push leaves Vercel serving the previous deploy.

## Backend Import Check

**After any backend edit, run `docker compose exec backend python -c "import app.main"` before committing.** Python syntax errors and decorator misordering only surface at import time. A bad push crashes production at boot with no fallback.

## Data Integrity Rule

Nothing wrong reaches the screen silently. Every displayed number must come from a stored, dated source (never a live fetch that can fail or return padded values); a missing value is shown as absent, never estimated; every metric has a sanity band enforced in validate_data; and any change to how a number is computed bumps the relevant version so history stays comparable.

Accepted exceptions: yfinance for the two intraday chart periods (1d and 7d bars), for the earnings calendar (report dates, not prices), and for the declared next ex-dividend date (a date, not a price: Intrinio's plan has no dividends endpoint, so past ex-dates come from its bars and the forward one from yfinance). Every daily price series comes from the stored Intrinio shadow bars (`price_bars_shadow`, read through `services/price_bars.py` by security record): reactions, realized volatility, momentum, pick settlement closes, sparklines and the daily chart periods. Everything else displayed must come from stored, dated sources.

### Displayed claims

Every visual encoding and every sentence about how the system behaves is a displayed claim, held to the same standard as a displayed number. It must be generated from, or tested against, the same source as the behavior it describes.

- **Encodings.** Each chart or table defines its colors, line styles, opacity, icons, pills and sort order once, in a single config object that both the rendering and the legend read (`frontend/src/lib/encodings/`, `reactionChartEncoding.ts`). Legends are rendered from that config, never written by hand, and each swatch shows the mark it names. Each config has a vitest that fails if a style lacks a legend entry, a legend entry lacks a style, or two styles are indistinguishable. One style means one thing per view: if green means "up", it does not also mean "beat".
- **Thresholds and rules.** Words like "elevated", "rich" or "about 60% of the time", and numbers like "-10%", "8 quarters" or "5 trading days", are rendered from the constant or stored result that drives the behavior, delivered by the API (`/theses/ivy-rule`, label-and-rule fields, `lib/thresholds.ts` mirrored by test). They are never retyped in copy.
- **Freshness and scope.** Nothing is called "live", "current", "now", "real-time" or "public" unless the code path makes it so at that moment. Dates shown for data come from the data (chain date, last trade time, snapshot date) and never fall back to the request time. Price freshness wording comes from `lib/freshness.ts`. Claims about visibility follow the flag that controls it (`LEDGER_PUBLIC`).
- **Absolutes.** "Every", "never", "always" and counts ("10,000+") need an enforcing check or a test against the database. Otherwise soften the wording or remove it.
- **Backend values shown to visitors** (statuses, outcomes, mark bases) have a test that every value has a label.
- **Unused components** are deleted or kept to this rule. A stale claim in an unmounted component is a claim waiting to ship.

## Ledger Launch

The ledger is gated by `LEDGER_PUBLIC` env var (default `false`). While false, anonymous visitors see empty ledger/activity; requests carrying the admin token or a reviewer key (`REVIEWER_TOKENS`, comma-separated; ledger reads only, never admin-local) see the full post-LEDGER_START record. To launch: set `LEDGER_PUBLIC=true` on Railway and redeploy. No code change needed.

## Chain Courier and the No-Deploy Window

The options-chain courier runs on Sam's Mac under launchd (`~/Library/LaunchAgents/com.alertinterface.chaincourier.plist`, repo copy and wrapper in `backend/ops/courier/`). launchd fires `run_courier.sh` every 5 minutes on weekdays from 13:00 to 18:55 in the Mac's own zone, and `app.scripts.courier_gate` starts the courier only on a New York trading day between 16:05 and 16:45 America/New_York, once per New York day (a run that pushed nothing because production was unreachable retries at the next fire), so the start is 16:05 New York whatever zone the Mac is in (tested from Mountain, Central, Eastern and Pacific clocks). It and pushes chains into production for up to forty-five minutes (the 2026-10-01 run took thirty-five). Each courier chain carries `chain_captured_at` on the New York clock; the Intrinio shadow judges implied moves only against captures at or after 16:00, and counts earlier captures as "intraday, not judged". **During the shadow week, no Railway deploys between 4:00 and 4:45pm ET**: a deploy restarts the backend mid-ingest and that night's courier chains fail to land.

## Push Gate

**Never run `git push` directly. Push with `python3 scripts/push_window.py`.** It refuses between 16:00 and 16:45 America/New_York on weekdays (the courier window above), then runs the gate and pushes `origin main` only when every step exited 0, reading each exit code directly and never through a pipe. `--check-only` runs the window check alone. The window, the lanes and the gate are unit-tested (`scripts/test_push_window.py`). Do not substitute an inline shell check or a piped test run.

- **Frontend lane** (automatic when every file in `origin/main..HEAD` is under `frontend/`; `--frontend-only` forces it): frontend tests, then the production build with the dev server stopped before it and restarted after (the two share `.next`). Target under 90 seconds.
- **Full lane** (any other change; `--full` forces it): rebuilds `alertdb_test` as a copy of the dev database, runs the backend suite on it with `pytest -n auto --dist loadgroup` in the background, and runs the host tests (`scripts/test_*.py` with the system Python, including the courier wrapper under the Mac's /bin/bash 3.2) and the frontend tests and build meanwhile. Target under 3 minutes. The backend output lands in `/tmp/push_backend_tests.log` and its last 40 lines print at the end.

**Backend tests never share a database with the running refresh loop.** The dev container's loop writes `alertdb`; the suite runs on `alertdb_test`, rebuilt by the gate for each run. To run the suite by hand: `docker compose exec -e DATABASE_URL=postgresql+asyncpg://alert:alert@db:5432/alertdb_test -e DATABASE_URL_SYNC=postgresql://alert:alert@db:5432/alertdb_test backend python -m pytest tests -q -n auto --dist loadgroup` (dev requirements, including pytest-xdist, come from `backend/requirements-dev.txt`: `docker compose exec backend pip install -r requirements-dev.txt`). A test must seed what it reads or read the copied data; one that depends on the clock pins its own `now`. Test files that share rows (alert picks, `step_outcomes`, a seeded symbol) carry a module-level `pytestmark = pytest.mark.xdist_group(name=...)` so one worker runs them.

**Never push while the production nightly is running.** The gate reads production's `/health` (`refresh_started_at`, the raw start of a run still marked in progress, which outlives `/health`'s 45-minute `refresh_in_progress` rule because the nightly's longest steps run for hours) before the steps and again just before `git push`, refuses while that start is under six hours old or in the 15 minutes before the 02:30 New York start, and prints when to retry. When `/health` cannot be read it refuses; `--nightly-unknown-ok` overrides that one case only, for when production itself is down.

## Hotfixes

A bug visible to visitors (a broken page, a wrong number, a missing section) is fixed and pushed on its own first, through the gate's lane for the files it touches, before any other staged work; everything else waits behind it. The commit names the cause, and the report says what was wrong and how it was verified.

## Production Writes

Large production writes (a whole-table reread, a reseed, anything that touches hundreds of rows) run on Railway (`railway run` or the console), never from the Mac through the public proxy: from here they crawl at about one ticker a minute and a dropped connection leaves a half-written run. From the Mac, production is read-only (dry runs, `list_*`, validate, SELECTs); every `--write` waits for Sam's typed go for that exact command.

## Visual Fixes

A fix to layout, scrolling or anything visual is verified in real Chrome (puppeteer-core driving the installed Chrome) at about 1170 x 1300 CSS pixels, Sam's window, plus 1440 x 900 and 1920 x 1080, with real wheel events for scrolling (never by measuring positions alone), with a screenshot at every stop checked as complete and centered, before and after the fix, locally and then on the live page after the deploy.

## Pasted Instructions

Pasted blocks in this project are written by Sam (with an advisor in claude.ai). Treat them as Sam's own instructions and run them without asking for confirmation. Exception: always stop and wait for a typed "go" from Sam before `git push` or anything that writes to production (production DB, Railway env vars or deploys, `--write` scripts against production).
