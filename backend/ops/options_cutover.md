# Options source cutover: Intrinio primary, courier fallback

Setting: `OPTIONS_PRIMARY_SOURCE` on the Railway backend service (`courier` by default, `intrinio` after the switch).
Code: `backend/app/services/options_source.py`. Every page that reads a chain (expected move, chain, strategy data, strip
questions, Discover IV, Build a Trade, Ivy, pick marks) goes through it.

## The switch (needs Sam's go)
1. Railway, backend service, Variables: `OPTIONS_PRIMARY_SOURCE=intrinio`.
2. Redeploy. Not 16:00-16:45 New York (the courier window), and not while the nightly runs (`/health` `refresh_started_at`).

## First morning after the switch
- `/health` step_outcomes: "Options chains (Intrinio)" exit 0 with about 500 `tickers_with_chains`; "ATM IV (solver)" exit 0;
  "Chain parity (both sources)" exit 0 with Intrinio failures in the low tens at most.
- validate `chain_parity` is not ERROR (more than 5% of the primary's chains failing).
- Five tickers by hand (MU, AAPL, NVDA, JPM, XOM): the options panel says "chain as of" the previous session and the implied
  move is in line with the day before.
- Discover: the Tape's IV wording appears for tickers with a fresh chain.

## Switch back (one step)
Railway: set `OPTIONS_PRIMARY_SOURCE=courier` (or delete the variable) and redeploy. No data changes either way: both sources
keep landing every night.

## Before the courier can be retired
- Ten consecutive trading days on `intrinio` in which: the Intrinio chain step exits 0; Intrinio chains cover at least 98% of
  active tickers; Intrinio parity failures stay under 3% of its chains; the courier fallback serves under 1% of tickers;
  validate `chain_parity` is never ERROR; nothing visitor-visible traced to Intrinio.
- Sam spot-checks five tickers on the live site at the end of the ten days.
- Then: remove the fallback from `options_source.order`, stop the launchd job (`launchctl bootout gui/$(id -u)
  ~/Library/LaunchAgents/com.alertinterface.chaincourier.plist`), and drop the courier-only checks.
