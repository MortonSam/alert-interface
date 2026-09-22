// How fresh each kind of data is, said once. Every page that shows a price, or
// talks about options data, renders these instead of writing its own sentence.
//
// Facts they describe:
//   quotes   Finnhub, behind a 60s cache, not real-time. A quote whose last trade
//            is more than 3 sessions old is withheld by the API (quote_state).
//   options  chains are uploaded once a day; each carries its own chain date.
//   research nightly refresh.

export const PRICE_FRESHNESS = "Prices from Finnhub, may be delayed up to 15 minutes";

export function researchFreshness(lastRefreshedAgo: string | null | undefined): string {
  return lastRefreshedAgo
    ? `Research data refreshed nightly, last ${lastRefreshedAgo}`
    : "Research data refreshed nightly";
}

export function freshnessLine(lastRefreshedAgo: string | null | undefined): string {
  return `${PRICE_FRESHNESS} · ${researchFreshness(lastRefreshedAgo)}`;
}

/** Names the options data by its own date. Never falls back to today. */
export function optionsDataPhrase(chainDate: string | null | undefined): string {
  return chainDate
    ? `options data as of ${chainDate}, updated once a day`
    : "the latest stored options data, updated once a day";
}

export function premiumSourcePhrase(chainDate: string | null | undefined): string {
  return chainDate
    ? `Entry premium taken from the ${chainDate} options data.`
    : "Entry premium taken from the latest stored options data.";
}

/**
 * A price the API withheld (quote_state stale / no_data), said the same way on
 * every page: the quote card, the expected-move card, the payoff simulator.
 * The reason already names the last-trade date. Null when the price is current.
 */
export function priceStateLine(
  state: "ok" | "stale" | "no_data" | null | undefined,
  reason: string | null | undefined,
): string | null {
  if (!state || state === "ok") return null;
  return reason ? `Price unavailable. ${reason}` : "Price unavailable.";
}

/** "price as of 2026-09-18" from the quote's own last-trade time; never today. */
export function priceAsOfPhrase(priceAsOf: string | null | undefined): string | null {
  const m = priceAsOf?.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? `price as of ${m[1]}` : null;
}
