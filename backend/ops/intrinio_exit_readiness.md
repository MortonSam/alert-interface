# Intrinio exit readiness: where Intrinio data lives, and what is computed from it

Report only, 2026-10-12. On cancellation Intrinio requires deleting all Intrinio data, including caches and backups, within 30 days,
with an officer certifying deletion. Counts are production (read-only) unless marked local. No Redis exists (no service in
docker-compose.yml, nothing in config or requirements); every cache is Postgres (system_metadata), a file, or a database copy.

## 1. Production Postgres (Railway), tables holding Intrinio values

| table | rows | what is Intrinio | source marked? |
|---|---|---|---|
| price_bars_shadow | 669,214 | every bar: open/high/low/close/volume, adjusted figures, factor, split_ratio, dividend | columns `intrinio_security_id`, `security_record_id`: every row is Intrinio by construction; no `source` column (flag: a vendor column would make deletion a one-line delete) |
| security_records | 524 | Intrinio security ids, FIGIs, names, listing dates | `source` |
| company_profiles | 513 | description, shares outstanding (Intrinio profile) | `source` = intrinio (513 of 513) |
| iv_history | 29,402 | 2,868 rows `intrinio_mid` (ATM IV solved from Intrinio chains, plus the vendor IVs in `vendor_*`); 26,534 `courier` rows (yfinance chains, not Intrinio) | `iv_source` |
| historical_reactions | 40,639 | 40,586 rows `price_source` = intrinio: close_before/open_after/close_after and the 1d/3d/5d percentage moves computed from Intrinio bars; 53 `stored_history` | `price_source` |
| rv_snapshots | 30,506 | realized volatility, rank, percentile, `last_bar_close`, dominant-day move: all from Intrinio bars since the shadow bars became the series | no source column (flag) |
| pe_snapshots | 2,012 | `price` is the Intrinio close; EPS is EDGAR | `window_source` marks the EPS window, not the price (flag: the price column has no vendor) |
| pe_sector_snapshots | 44 | medians of P/E ratios (Intrinio closes over EDGAR EPS) | `computation_version` only (flag) |
| earnings_features | 10,115 | momentum_20d, actual_1d/3d/5d, prior averages, atm_iv: from Intrinio bars and chains (older rows from yfinance bars) | no source column (flag) |
| magnitude_trend_snapshots | 12,968 | averages of 1-day moves from the reactions | `computation_version` only (flag) |
| sector_peer_snapshots | 13,216 | sector averages of 1-day moves | `computation_version` only (flag) |
| analyst_reaction_stats | 515 | median moves on analyst-action days from the reactions (actions from yfinance, prices from Intrinio) | no source column (flag) |
| put_call_snapshots | 5,706 | versions 1-2 from courier (yfinance) chains; version 3 (Intrinio chains) starts tonight, 0 rows today | `computation_version`, `basis` |
| alert_picks | 18 | entry_price, close_price, option P&L from chains (season 1 courier, season 2 Intrinio), receipts citing closes | `source` names the run (manual/nightly), not the vendor (flag) |
| alert_pick_evaluations | 366 | implied_move_pct, expected_move_pct, momentum from Intrinio chains and bars | `source` = nightly, not the vendor (flag) |
| shadow_picks | 246 | probability inputs and actual_5d from the reactions | none (flag) |
| credit_shadow_picks | 70 | spot, strikes, credit, close_value from chains (courier era) | none (flag) |
| pricing_verdicts | 0 | expected values and settled legs from Intrinio chains and closes (fills from tonight) | `computation_version` only (flag) |
| quote_snapshots | 503 | Finnhub quotes (not Intrinio) | — |
| theses | 6 | entry prices a visitor saved from the chain shown | none (flag) |
| research_notes | 19 | inputs and sentences cite the latest close and market cap (Intrinio close × Finnhub shares); the filings are EDGAR | `data_version`, `source_filings` (EDGAR); the close is not marked (flag) |
| ask_log | 2 | answers quote closes, implied moves | none (flag) |
| ivy_move_notes | 0 | sentences citing moves | `sources` |
| events | 176,617 | 2.01/split rows read from Intrinio bars carry `source` = intrinio; the rest EDGAR, Finnhub, FRED, yfinance, manual | `source` |
| ivy_train_log, ivy_backtest_runs | 20, 1 | model fits over the reactions | `computation_version` only (flag) |
| eps_quarters, release_eps, growth_figures, earnings_report_timing, ticker_timing_patterns, news_stories, analyst_recommendations, rates | 30,916 / 96 / 0 / 11,194 / 510 / 2,167 / 2,544 / 24 | EDGAR, EDGAR, EDGAR, EDGAR, EDGAR, Finnhub, Finnhub, FRED: not Intrinio | — |

## 2. Production system_metadata keys (11,823 rows)

| prefix | rows | size | what |
|---|---|---|---|
| intrinio_chain:{SYM}:{EXP} | 2,212 | 72 MB | Intrinio EOD chains (cleaned); `chain_source` inside each value |
| chain:{SYM}:{EXP} | 2,108 | 18 MB | courier (yfinance) chains, not Intrinio |
| options_read:* | 6,905 | 13 MB | Ivy's Read, generated from the serving chain's figures (since Oct 9 Intrinio) and the stored bars; no vendor field inside (flag) |
| chain_parity:{SYM} | 503 | 246 kB | parity verdicts per source, with the Intrinio ATM quotes and the close |
| chain_shadow:{date} | 3 | 625 kB | per-ticker comparison figures, courier beside Intrinio |
| live_quotes, live_data_status | 2 | 117 kB | Intrinio 15-minute delayed quotes (the live layer, collecting since today) |
| pricing_card:* | 0 today in production (29 locally) | — | cards computed from Intrinio chains and bars |
| step_outcomes, chain_shadow, rv_last_run | 3 | 76 kB | outcome records quoting counts and some figures |

## 3. Files and backups

- Railway Postgres backups: the CLI has no backups command (`railway backups` is unknown); the retention and restore points must be read and
  cleared in the Railway dashboard (Postgres service → Backups). Flag: cannot be certified from here.
- This Mac, Docker volume: `alertdb` (314 MB, a copy of production restored for development) and five test copies `alertdb_test`,
  `alertdb_test_ask`, `alertdb_test_confirm`, `alertdb_test_launch`, `alertdb_test_trust` (264-265 MB each): full copies of every table above.
- Repo: `backend/ops/ivy_v3/events*.jsonl` (111 MB, untracked): per-event figures from 9,144 Intrinio chains (straddle bids and asks, strike-ladder
  quotes, IVs); `backend/ops/ivy_v3/*.md` and `results.json`/`picks.json` (untracked): aggregates only. `backend/app/services/cache` (3.0 GB,
  17,157 files) is EDGAR (filings, company facts, submissions), not Intrinio.
- Backend container `/tmp`: `cq_chains.json` (102 MB, every stored chain re-read with its Intrinio roots), `cq_compare.json`, `cq_page.json`,
  `reread.json`, `band_rerun.json`, `parity_rows.json`, `replay*.json`: research scratch holding chain figures; deleted with the container.
- Session scratchpad on this Mac (798 MB, not the repo): `cq/` scripts and outputs, screenshots of pages showing Intrinio figures, audit JSON.
- `~/.alert-interface`: `intrinio-openapi.json` (the API spec, not data); courier logs and output (yfinance); `deadman.env`, `courier.env` (keys).
- Outside our control: PostHog session replays record rendered pages, so Intrinio figures appear in them; Vercel holds no data; ntfy digests
  quote counts only. Flag: PostHog retention needs its own answer.

## 4. Derived Works candidates (counsel's view needed on every line)

Plainly Intrinio data, delete on exit: price_bars_shadow (the bars themselves), intrinio_chain:* and the research events files and container
scratch (chain quotes), live_quotes, security_records (Intrinio identifiers), company_profiles' Intrinio descriptions, every `last_bar_close`,
`price`, `spot`, `close_before/after`, `entry_price`, `close_price` column that stores a close or a quote as a value, and the database copies and
backups of all of these.

Possibly retainable as Derived Works (computed, not the data; each needs the stored source values beside it removed or nulled):
- historical_reactions' percentage moves (pct_change_1d/3d/5d) once close_before/open_after/close_after are nulled: a reaction is an
  arithmetic result of two prices, not a price; the same figure was once computed from yfinance bars.
- rv_snapshots' rv_20d, rv_rank, rv_percentile, rv_min/max_1y (statistics over 20-252 bars) once last_bar_close and dominant_move_pct are nulled.
- pe_snapshots' pe, hist_median, hist_share_above once `price` is nulled (the EPS is EDGAR); pe_sector_snapshots' medians.
- earnings_features' prior averages and momentum_20d (a ratio of two closes) with actual_1d/3d/5d as ratios; magnitude_trend and sector_peer
  snapshots (averages of ratios); analyst_reaction_stats' medians.
- alert_picks', theses' and pricing_verdicts' P&L percentages once entry and close prices are nulled; alert_pick_evaluations' implied_move_pct
  (a ratio of a straddle to a spot) is closer to the data, weaker case.
- iv_history's solved atm_iv (a solver output) is arguable; the `vendor_*` IV columns are Intrinio's own figures and are not.
- Ivy's Read and research-note sentences that quote a close are text containing a value; the value would have to be excised or the text deleted.

Not Intrinio at all, nothing to delete: eps_quarters, release_eps, growth figures, report timing (EDGAR); news_stories, analyst_recommendations,
quote_snapshots (Finnhub); rates (FRED); the courier's chain:* keys and courier iv_history rows (yfinance).
