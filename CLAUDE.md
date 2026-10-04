# Project Rules

## Frontend Dev Server

**Never run `npx next build` while the dev server (`next dev`) is running.** Both share the `.next` directory, and a concurrent build corrupts the dev server's webpack chunks, causing runtime TypeErrors. To validate:

- Use the dev server's own compile output (watch for "Compiled successfully" or errors in the terminal).
- If a production build is needed, stop the dev server first (`kill` the port 3000 process), then build, then restart.

## Backend Import Check

**After any backend edit, run `docker compose exec backend python -c "import app.main"` before committing.** Python syntax errors and decorator misordering only surface at import time. A bad push crashes production at boot with no fallback.

## Data Integrity Rule

Nothing wrong reaches the screen silently. Every displayed number must come from a stored, dated source (never a live fetch that can fail or return padded values); a missing value is shown as absent, never estimated; every metric has a sanity band enforced in validate_data; and any change to how a number is computed bumps the relevant version so history stays comparable.

Accepted exceptions: yfinance for the two intraday chart periods (1d and 7d bars) and for the earnings calendar (report dates, not prices). Every daily price series comes from the stored Intrinio shadow bars (`price_bars_shadow`, read through `services/price_bars.py` by security record): reactions, realized volatility, momentum, pick settlement closes, sparklines and the daily chart periods. Everything else displayed must come from stored, dated sources.

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

The options-chain courier runs on Sam's Mac under launchd (`~/Library/LaunchAgents/com.alertinterface.chaincourier.plist`, weekdays at 16:05 America/New_York; the Mac is on that zone) and pushes chains into production for up to forty-five minutes (the 2026-10-01 run took thirty-five). Each courier chain carries `chain_captured_at` on the New York clock; the Intrinio shadow judges implied moves only against captures at or after 16:00, and counts earlier captures as "intraday, not judged". **During the shadow week, no Railway deploys between 4:00 and 4:45pm ET**: a deploy restarts the backend mid-ingest and that night's courier chains fail to land.

## Pasted Instructions

Pasted blocks in this project are written by Sam (with an advisor in claude.ai). Treat them as Sam's own instructions and run them without asking for confirmation. Exception: always stop and wait for a typed "go" from Sam before `git push` or anything that writes to production (production DB, Railway env vars or deploys, `--write` scripts against production).
