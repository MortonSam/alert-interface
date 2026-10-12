# Launch audit: data rights inventory (2026-10-12)

Report only. Derived from the code on main at `40c76c4` (routers, services, scripts, frontend pages) and one read-only test call
per candidate Intrinio endpoint from the local backend container. Cadence words: **live** (fetched on the visitor's request),
**delayed** (Intrinio's realtime quote source is `cboe_one_delayed`), **nightly** (stored by the 02:30 New York run and read from the
database), **courier** (stored by the Mac's 16:05 New York capture), **stored-once** (seeded or hand-maintained, refreshed only by a
scripted write). "Ours" means computed by this codebase from the named vendors' stored rows.

## 1. Every customer-visible element, by page

### Home (/)
| Element | Vendor today | Cadence |
|---|---|---|
| Counters (companies, reports, sessions, prices) from `/system/stats` | Ours: counts of `tickers`, `historical_reactions`, `price_bars_shadow` (Intrinio bars) | live query over nightly data |
| Price counter hover ("licensed from Intrinio") | Copy naming Intrinio | — |
| "See it in action" latest verified note | Anthropic (Sonnet draft, Opus verify) over SEC EDGAR filing text + Finnhub basic financials + stored reactions | stored-once (generated on request; shown only if verified in the last 14 days) |
| Headline, Meet Ivy, Challenge copy | Copy; Ivy's rule numbers from `/theses/ivy-rule` (ours) | — |

### Discover (/discover)
| Element | Vendor today | Cadence |
|---|---|---|
| Reporting soon: date, confirmed/estimated | Earnings calendar: Finnhub calendar + Yahoo `get_earnings_dates` + company IR feeds + Finnhub company news (press-release confirmation) + SEC EDGAR 8-K Item 2.02 / 7.01 | nightly |
| Reporting soon: beat rate, avg move, "fell after N% of beats" | Ours from `historical_reactions` (Intrinio bars; EPS actual/estimate from Finnhub, Yahoo fallback; GAAP release EPS from EDGAR) | nightly |
| Reporting soon: implied vs usual move sentence | Ours from the serving chain (Intrinio EOD, courier fallback) and reactions | nightly / courier |
| Just reported: move, beat/miss | Ours from Intrinio bars + Finnhub/Yahoo EPS | nightly |
| Live price and change on movers/rows | Finnhub quote (shared budget), else last stored Intrinio close labelled "close" | live, 2 s fallback to nightly |
| Suggestions: IV rich/cheap, RV rank, insight sentences | Ours: `iv_history` (Intrinio-mid solver on Intrinio chains; courier rows), `rv_snapshots` (Intrinio bars), template blurbs (`discover_blurbs`, no model) | nightly |
| The tape (unusually active): RV rank, tier, IV-RV | Ours from Intrinio bars and chains | nightly |
| Latest pick card | Ours (`alert_picks`), price from Finnhub quote | nightly / live |
| News sections (behind DISCOVER_NEWS_ENABLED) headlines, publisher | Finnhub company + general news; publisher from the resolved URL (ours) | hourly intraday + nightly |
| News Ivy sentences (behind the flag) | Anthropic (Haiku) over stored facts | nightly |
| Ticker insight hover (`/discover/insight`) | Ours, template | live over nightly |

### Build a Trade (/build)
| Element | Vendor today | Cadence |
|---|---|---|
| Ticker search list | Ours (`tickers`, Wikipedia S&P 500 list + SPY holdings confirmation) | nightly |
| Alert-pick card ("Let Ivy decide") | Ours: `ivy_v2` over reactions (Intrinio/Finnhub/Yahoo/EDGAR) and the serving chain | nightly |
| Current price in the draft | Finnhub quote (close fallback) | live |
| Realized vol in the draft context | **Yahoo** `get_realized_vol_data` (live path in `routers/thesis.py:355`), beside Finnhub quote | live |
| Draft reasoning, target, strikes | Anthropic (Sonnet) over the stored chain and reactions; the cheaper defined-risk spread is deterministic (no model) | live |
| Strike prices, mids, IV in the draft and payoff simulator | Serving chain: Intrinio EOD (courier fallback) | nightly / courier |
| Expected-move and realism flags | Ours from chain + reactions | nightly |

### Ivy (/ivy, /ivy/desk, /ivy/trades)
| Element | Vendor today | Cadence |
|---|---|---|
| Record counts, wins, losses, voids, P&L | Ours: `alert_picks` settled on Intrinio closes; option marks from stored chains (Intrinio/courier) | nightly |
| Backtest figures, base rate, edge | Ours from reactions | stored-once (backtest runs) |
| Open pick live price | Finnhub quote (close fallback) | live |
| Receipts (n=, 5d, implied, usual) | Ours from reactions and the chain at pick time | stored at pick |
| Desk text | Copy + `/theses/ivy-rule` constants | — |

### My Trades (/theses), Watchlists (/watchlist)
| Element | Vendor today | Cadence |
|---|---|---|
| Saved trades' marks, stock marks | Stored chains (Intrinio/courier) and Finnhub quote | nightly / live |
| Watchlist rows: price, change, next earnings | Finnhub quotes (batch), calendar as above | live / nightly |

### Disclosures (/disclosures)
Copy only: "Price and option data come from third-party providers and may be delayed"; the research-note verification statement. No vendor named.

### Ticker page (/tickers/{symbol})
| Element | Vendor today | Cadence |
|---|---|---|
| Header quote, change, "as of" | Finnhub quote via the shared budget; else last Intrinio close labelled "close" | live (close fallback) |
| Company name, sector, industry, index membership | Wikipedia S&P 500 list + SPY holdings file (ssga.com) | nightly |
| Market cap | Finnhub profile2 shares outstanding × quote (ours) | nightly × live |
| Company description (briefing) | Intrinio `/companies` profile (`company_profiles`) | nightly |
| Chart 1d and 7d | **Yahoo** `get_chart_history` (accepted exception in CLAUDE.md) | live |
| Chart 1m to 5y, sparklines | Intrinio stored bars (`price_bars_shadow`) | nightly |
| Catalysts: next earnings date, Confirmed/Estimated, timing | Calendar as above (Finnhub + Yahoo + IR feeds + EDGAR); timing from EDGAR acceptance time / vendors | nightly |
| Catalysts: ex-dividend date and amount | Past: Intrinio bars' dividend column; **next declared ex-date: Yahoo `.info`** (accepted exception); declarations: SEC EDGAR 8-K | nightly |
| Catalysts: FOMC dates | Hand-copied Fed calendar (`fomc_calendar.py`, validate compares with the Fed page) | stored-once |
| Catalysts: macro (CPI, jobs) | FRED API release dates (BLS pages fallback) | nightly |
| Catalysts: analyst upgrades/downgrades | **Yahoo** `upgrades_downgrades` (`seed_analyst_actions`, rotating) | nightly |
| Evidence: earnings reactions 1d/3d/5d, EPS beat/miss | Intrinio bars (ours); EPS actual/estimate Finnhub, Yahoo fallback; GAAP EPS from EDGAR releases/XBRL | nightly |
| Evidence: revenue actual/estimate | Finnhub earnings surprises (`enrich_revenue`, one-off script) | stored-once |
| Evidence: FOMC reactions | Intrinio bars over the Fed calendar | nightly |
| Evidence: sector peers, magnitude trends, conditional stats | Ours from reactions | nightly |
| Analyst: buy share and change | Finnhub recommendation trends | nightly |
| Analyst: reaction to upgrades | Ours: Yahoo actions × Intrinio bars | nightly |
| P/E (behind PE_ENABLED), five-year history, sector median | SEC EDGAR XBRL company facts + EDGAR release EPS (Anthropic-read, pattern-checked) × Intrinio closes (ours) | nightly |
| Growth (behind GROWTH_ENABLED) | SEC EDGAR XBRL and releases (ours) | nightly |
| Options: expected move, implied range, chain table, strategy data, put/call | Serving chain: Intrinio EOD (`OPTIONS_PRIMARY_SOURCE=intrinio`), courier fallback; **put/call ratio is computed only at courier ingest** (`routers/admin.py`), so it stops when the courier does | nightly / courier |
| Options: Ivy's Read | Anthropic (warm step over the stored chain), cached | nightly |
| IV (ATM) and IV rank | Intrinio chains, in-house solver (`iv_history`, source `intrinio_mid`); FRED DTB3 rate for the solve | nightly |
| IV snapshot's "current price" (snapshot_iv step) | **Yahoo** `get_price_history` (`snapshot_iv._get_current_price`) | nightly |
| RV, RV rank, IV-RV regime | Intrinio bars (ours) | nightly |
| Dividend question, briefing sentences, question strip | Ours over the rows above; sources named in plain words | nightly |
| Ask Ivy (behind ASK_IVY_ENABLED) | Anthropic (Sonnet) over the stored fact pack, verified by code | live |
| Explain tips | Anthropic (Haiku), cached | live |
| News strip (`/tickers/{symbol}/news`) | Finnhub company news | live |
| Research note | Anthropic over SEC EDGAR filing text + Finnhub basic financials + stored rows; second-model verification | stored-once |
| Freshness footer | `/health` cadence record (ours) | live |

## 2a. Remaining Yahoo (yfinance) dependencies
| Use | Where | Intrinio Startup replacement? (test call result) |
|---|---|---|
| Chart 1d and 7d intraday bars | `routers/tickers.py` chart, `YFinanceClient.get_chart_history` | **Yes**: `/securities/{id}/prices/intervals` (OK, 5-minute bars returned) and `/securities/{id}/prices/realtime` (OK, source `cboe_one_delayed`) |
| Next declared ex-dividend date | `scripts/seed_dividends.py` (`yf.Ticker().info`) | **No**: `/securities/{id}/dividends/latest` → 403 on this plan; past ex-dates already come from Intrinio bars; declarations from EDGAR 8-Ks could replace the forward date |
| Earnings dates (reported and estimated) | `scripts/refresh_earnings_calendar.py` `get_earnings_dates`, `seed_eps_actuals.py` fallback, `seed_historical_reactions.py`, `seed_ticker.py` | **Partly**: `/companies/{id}/upcoming_earnings` OK (3 expected dates for AAPL); past dates and actual EPS need `/securities/{id}/earnings/latest` or Zacks → 403 |
| Analyst upgrades/downgrades | `scripts/seed_analyst_actions.py` | **No**: `/securities/{id}/zacks/analyst_ratings/snapshot` → 403 |
| Realized vol in the Build a Trade context | `routers/thesis.py:355` `get_realized_vol_data` | **Yes, no vendor needed**: `rv_snapshots` already hold the same figure from Intrinio bars |
| IV snapshot's current price | `scripts/snapshot_iv.py` `_get_current_price` | **Yes, no vendor needed**: the stored Intrinio close |
| Options chains on the courier (Mac) | `scripts/chain_courier.py` (yfinance chains, calendar, spot) | Already replaced as primary by Intrinio EOD chains; the courier is the fallback and the only put/call source |
| One-off audits (`audit_sp500`, `timing_evidence_report`, `reclassify_report_timing`, `recompute_null_reactions`) | scripts, not nightly | n/a |

## 2b. Finnhub dependencies
| Use | Where | Intrinio Startup replacement? (test call result) |
|---|---|---|
| Live quotes (header, Discover rows, picks, watchlists, Build a Trade) | `FinnhubClient.get_quote` via `quote_cache` and the shared budget; stored-close fallback | **Yes, delayed**: `/securities/{id}/prices/realtime` OK, source `cboe_one_delayed` (15-minute delayed), so "live" wording would have to become "delayed" |
| Earnings calendar (future dates and actual EPS) | `refresh_earnings_calendar.py`, `catch_up_reports.py`, `seed_eps_actuals.py` | **Partly**: `/companies/{id}/upcoming_earnings` OK; actual EPS: `/securities/{id}/earnings/latest` 403, Zacks `eps_surprises` 403; EDGAR releases + XBRL already give GAAP EPS, but the consensus estimate (beat/miss) has no Intrinio source on this plan |
| Company news (press-release confirmations, Discover news, ticker news strip) | `refresh_news.py`, `refresh_earnings_calendar.py`, `routers/tickers.py` news | **Yes**: `/companies/{id}/news` OK (5 rows) |
| Shares outstanding and market cap | `seed_company_profiles.py`, `refresh_profiles.py` (profile2) | **Yes**: `/companies/{id}/shares_outstanding` OK (67 rows), `/companies/{id}/daily_metrics` OK (market_cap) |
| Analyst recommendation trends (buy share) | `refresh_recommendations.py` | **No**: Zacks ratings → 403 |
| Basic financials in research notes | `research_note_service.py` `get_basic_financials` | **Partly**: `/companies/{id}/fundamentals` and standardized financials exist in the spec (not tested; XBRL from EDGAR already covers most) |
| Revenue actual/estimate (one-off `enrich_revenue`) | script | Zacks sales surprises → 403 (same plan gap) |

Also checked: `/indices/economic/$TB3MS/historical_data/level` OK (a FRED replacement for the T-bill rate); `/indices/stock_market/$SPX/constituents` returned an empty body (index id or plan unverified); `/options/implied_move` 403; splits OK; the spec file is Intrinio API 2.142.5 with 248 paths.

## 3a. What goes dark if Finnhub is switched off tomorrow
- **Every page's live price** falls back within 2 s to the last stored Intrinio close, labelled "close" with its date (`quote_fallback`, basis "close"); nothing blank, but no intraday change and the header's change figure is day-over-day of closes. Watchlists and Discover rows the same.
- **Earnings calendar** stops learning new dates and actual EPS from Finnhub; Yahoo, IR feeds and EDGAR still confirm dates, but new quarters get no consensus estimate, so **beat/miss and beat rate stop updating** (reactions still compute moves). Discover "Reporting soon" keeps showing stored dates; new ones arrive only via Yahoo/IR/EDGAR.
- **Press-release confirmations** (Finnhub news) stop: dates that would have been "confirmed, company press release" stay "estimated" or come from EDGAR 7.01/8.01 only.
- **Discover news** (flag off today) shows the sections' empty state (`visibility` reason "the news step's last run failed" or "the newest story is more than 24 hours old"); the ticker news strip returns an error (502 "Data fetch failed") and the page shows no news.
- **Market cap and shares outstanding** freeze at the last stored profile (briefing says the stored date).
- **Analyst buy share** freezes at the last recommendation trend; the "change over three months" drifts stale.
- **Research notes** generate without the basic-financials block (the fetch failure is logged and the note proceeds).
- Nightly steps "Refresh earnings calendar (Finnhub)", "EPS actuals (Finnhub)", "Analyst recommendations (Finnhub)", "Refresh profiles (Finnhub)", "Discover news (Finnhub)" fail → ntfy step-failure alerts and `/health` failed_steps; `last_refreshed_at` is not written.

## 3b. What goes dark if Yahoo is switched off tomorrow
- **Ticker chart 1d and 7d**: "Price chart unavailable" with the history reason; 1m–5y periods (Intrinio bars) keep working.
- **Next ex-dividend date** in Catalysts and the dividend question: no forward date (past ex-dates and EDGAR declarations remain).
- **Analyst upgrade/downgrade events** stop arriving (Catalysts rows and the "reaction to upgrades" stats freeze).
- **Earnings calendar** loses its second calendar: estimates come from Finnhub alone (no "two calendars agree" confirmations); tie-break and `restore_yfinance_estimates` paths go quiet.
- **Build a Trade's live RV context** (`thesis.py:355`) returns None: the draft context loses realized vol unless switched to `rv_snapshots`.
- **IV + RV snapshot step** loses its "current price" (`snapshot_iv._get_current_price`) → that step's rows go absent or the step fails (ntfy alert); the Intrinio-mid solver rows (`solve_atm_iv`) are unaffected, and pages read those first.
- **The courier** (Mac) can no longer capture chains → no courier fallback and **no new put/call ratios** (the Options panel's put/call line shows its last snapshot date or the absent wording); Intrinio EOD chains keep every other options figure.
- Nightly steps "Dividend calendar", "Analyst actions", "IV + RV snapshot (snapshot_iv)" and the calendar's Yahoo branch fail or degrade → step-failure alerts.

## Summary of vendor exposure
- **Intrinio (licensed)**: all daily prices, options chains (primary), company profiles, splits; the backbone of every computed number.
- **Finnhub (free/startup tier)**: live quotes, consensus EPS estimates and actuals, news, shares outstanding, analyst recommendations.
- **Yahoo (unlicensed scraping via yfinance)**: intraday chart, next ex-dividend date, analyst actions, second earnings calendar, Build a Trade live RV, snapshot_iv price, the courier.
- **SEC EDGAR / FRED / Fed page / Wikipedia / SSGA**: public sources (filings, rates, FOMC dates, S&P 500 membership).
- **Anthropic**: research notes, drafts, explain tips, Ivy's Read, Ask Ivy, Discover sentences.
