# Licensed-source audit, 2026-10-20 (branch licensed-sources)

Every figure or line a visitor can see on the public routes (`/`, `/discover`, `/build`, `/ivy`, `/ivy/desk`, `/ivy/trades`,
`/ivy/picks`, `/theses`, `/disclosures`, `/tickers/{symbol}`), with the vendor and plan it rests on, and what the branch does with it.
Finnhub's free plan and Yahoo Finance are personal use only. Licensed for display: Intrinio (prices, bars, options chains,
company profiles), SEC filings (XBRL, 8-K releases), the companies' own releases and IR pages, the Federal Reserve and BLS calendars.

The branch adds one flag, `PERSONAL_USE_DATA_SHOWN` (config, default **false**; services/personal_use). While it is false, nothing
in the "Finnhub / Yahoo" rows below leaves the API. Turning it on restores today's behaviour; it stays off until your go.
Wording column: "none" means the element disappears or keeps its existing approved wording; no new visible string was written.

| Route | Element | Current source (plan) | Branch: replacement or hidden | Wording |
|---|---|---|---|---|
| ticker header, `/build`, Discover rows, home grid, Ivy marks | Price and day change | Finnhub `/quote` (free, personal use) while LIVE_DATA_ENABLED is off | Replaced: every visitor-priority Finnhub quote is the stored Intrinio close (finnhub_client.get_quote → quote_fallback), dated as a close. With LIVE_DATA_ENABLED on, the Intrinio delayed quote, unchanged | Existing close wording ("Showing the close on ...") |
| ticker header | Market cap ("· $5.16T") | Finnhub profile (free) | Hidden (TickerRead serializes no market cap) | none |
| ticker Overview | "worth about $5.3 trillion" | quote × shares outstanding, shares from the Finnhub profile; agreement check against the Finnhub market cap | Hidden (the clause is left out) | none |
| ticker Overview | Company description | Intrinio company profile | Kept (licensed) | unchanged |
| ticker Overview, sector line | GICS sector and sub-industry | S&P 500 constituent list | Kept | unchanged |
| ticker header, Catalysts, Overview, Discover, Build a Trade | Next report date and "confirmed (two calendars agree)" / "estimated (Finnhub)" | Finnhub and Yahoo calendars (personal use); company confirmations from 8-Ks and IR pages | Replaced: LICENSED_DATES_ONLY behaviour (services/personal_use.dates_licensed_only): a date only when the company's own words confirmed it, otherwise the expected window from past report dates in SEC filings | **Needs wording**: the frontend has no line for the `expected_window` level, so on this branch such a date falls through to the "estimated" line. Held; see decisions |
| ticker header | "Analyst data as of 20h ago" | Finnhub recommendations, Finnhub/Yahoo upgrades and downgrades | Hidden (the analyst dataset is dropped from /health's datasets, so the line is never built) | none |
| ticker Catalysts | Street Pulse: analyst actions (firm, grade, target), upgrade/downgrade reaction stats | Finnhub/Yahoo analyst actions; reactions computed on Intrinio bars | Hidden (analyst-detail and analyst-stats return empty; the section is not drawn) | none |
| ticker Catalysts | Analyst action events in the event list | Finnhub/Yahoo | Hidden (events endpoints drop them) | none |
| ticker Catalysts | Next ex-dividend date | Yahoo (the forward date; past ex-dates from Intrinio bars) | Hidden when its source is yfinance | none |
| ticker Catalysts | Macro calendar (FOMC, payrolls, CPI, PPI) | Federal Reserve, BLS | Kept | unchanged |
| ticker Evidence | Past report dates of the reaction rows and charts | Report dates first taken from Finnhub/Yahoo calendars; moves computed on Intrinio bars | **Kept; your decision** (see below) | unchanged |
| ticker Evidence | EPS against a year earlier, FFO per share | SEC XBRL, 8-K releases (stage 1) | Kept | approved |
| ticker Evidence | Analyst estimates, beats, misses, surprises, beat rates | Finnhub/Yahoo (personal use) | Already withheld by LICENSED_ESTIMATES (off) and never drawn (stage 1) | none |
| ticker Options | Options verdict, implied range, IV, put/call | Intrinio chains (and the courier) | Kept | unchanged |
| ticker News | Company news headlines ("Yahoo · Oct 8, 11:29 AM ET") | Finnhub company news (free) | Hidden (`/tickers/{symbol}/news` returns no items) | none |
| ticker Research | Research note text and EPS strip | Model over SEC filings; strip from SEC EPS (stage 1) | Kept | unchanged |
| `/discover` | Biggest movers, In the news | Finnhub quotes and news; DISCOVER_NEWS_ENABLED already off in production | Hidden by the flag as well | none |
| `/discover` | Analyst blurbs (buy-share change, typical move on upgrades) | Finnhub recommendations, analyst actions | Hidden (the batch helpers return nothing) | none |
| `/discover` | Just reported rows | report dates (calendar) + SEC EPS line + Intrinio moves | Kept; the date follows the report-date decision | unchanged |
| `/` | Counters: option contracts, daily prices, earnings reactions | Intrinio and the courier; reactions on Intrinio bars | Kept | unchanged |
| `/` | Counter: analyst actions measured | Finnhub/Yahoo analyst actions | Hidden (the API sends null; the row shows three counters) | none |
| `/` | Latest verified note | Model over SEC filings | Kept | unchanged |
| `/ivy`, `/ivy/desk`, `/ivy/trades`, `/ivy/picks`, `/theses` | Picks, marks, P&L | Intrinio chains and bars; marks priced from visitor quotes | Marks now use the Intrinio close (the quote gate above); Ivy picks only confirmed dates already | unchanged |
| `/build` | Draft trade facts | Intrinio chains, quote (gated above), report date (gated above) | As above | unchanged |
| `/disclosures` | Data sources text | static | No change in this branch; it should name the sources once you decide | — |

## Needs your decision

1. **Past report dates** (every reaction row, chart marker and count of "earnings reactions measured"): the dates were first taken
   from Finnhub and Yahoo calendars. Each is checkable against the company's Item 2.02 8-K (SEC), and catch_up_reports already
   reads those. Options: keep (a date is a public fact the company filed), or backfill each from its 8-K and drop any it cannot match.
2. **The expected-window line**: with vendor dates held, a name without a company-confirmed date gets an expected window from its
   SEC filing history (services/report_windows). No approved wording renders that level; it currently falls through to "estimated".
   Wording needed before this branch can ship.
3. **Market value in the Overview**: it can return from licensed inputs (Intrinio close × SEC dei:EntityCommonStockSharesOutstanding);
   not built tonight.
4. **Quotes in market hours** with LIVE_DATA_ENABLED off: visitors would see the previous close until LIVE_DATA_ENABLED is on (stage 6).
5. **Internal use**: the nightly still reads Finnhub and Yahoo for calendars, EPS actuals, recommendations, analyst actions and
   profiles (shares outstanding, market cap) and stores them; nothing above displays them while the flag is off. Whether internal use
   (the market value agreement check, the reaction seeder's dates) is within the personal-use terms is a licence question for you.

## How it was checked

- Backend: test_personal_use (flag default off; withheld events, market cap, the visitor quote served from the Intrinio close without
  asking Finnhub); the rest of the suite runs with the flag on (conftest). Full suite on a copy of the dev database: 1,222 passed.
- Frontend: the counters row filters a withheld count; Street Pulse is not drawn with no actions and no counts; 406 tests pass.
- The preview frontend reads production's API, which does not have this branch's backend, so the preview shows only the frontend
  side until a backend deploy.
