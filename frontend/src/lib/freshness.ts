// How fresh each kind of data is, said once. Every page that shows a price, or
// talks about options data, renders these instead of writing its own sentence.
//
// Facts they describe:
//   quotes   Finnhub, behind a 60s cache, not real-time. A quote whose last trade
//            is more than 3 sessions old is withheld by the API (quote_state).
//   options  chains are uploaded once a day; each carries its own chain date.
//   research nightly refresh.

export const PRICE_FRESHNESS = "Prices from Finnhub, may be delayed up to 15 minutes";

/** The nightly datasets a page shows, by the keys /health and /system/status publish (services/dataset_freshness). */
export const DATASET_LABELS: Record<string, string> = {
  prices: "Prices", chains: "Options data", reactions: "Earnings history", analyst: "Analyst data",
  iv: "Implied volatility", rv: "Realized volatility", earnings_calendar: "Earnings calendar",
};

export interface DatasetAgeLike { at: string | null; ok: boolean; failed?: string[] }

/** The oldest of the named datasets, dated by its own last success: "Earnings history as of 6h ago". A dataset whose
 * last nightly step failed says so. Null when none of the named datasets has ever succeeded. */
export function datasetAgeLine(
  datasets: Record<string, DatasetAgeLike> | null | undefined, keys: string[], ago: (iso: string) => string,
): string | null {
  if (!datasets) return null;
  const known = keys.map((k) => [k, datasets[k]] as const).filter(([, d]) => d);
  if (known.length === 0) return null;
  const neverRun = known.filter(([, d]) => !d.at);
  if (neverRun.length === known.length) return null;
  const dated = known.filter(([, d]) => d.at) as Array<readonly [string, DatasetAgeLike]>;
  const [key, oldest] = dated.reduce((a, b) => (new Date(b[1].at as string) < new Date(a[1].at as string) ? b : a));
  const label = DATASET_LABELS[key] ?? key;
  const failed = known.filter(([, d]) => !d.ok).map(([k]) => DATASET_LABELS[k] ?? k);
  return `${label} as of ${ago(oldest.at as string)}` + (failed.length ? ` · last nightly step failed for ${failed.join(", ")}` : "");
}

/** The oldest named dataset is older than `days`: the line turns amber. */
export function datasetsStale(datasets: Record<string, DatasetAgeLike> | null | undefined, keys: string[], days = 3, now = Date.now()): boolean {
  if (!datasets) return false;
  return keys.some((k) => {
    const d = datasets[k];
    return !!d && (!d.at || now - new Date(d.at).getTime() > days * 24 * 60 * 60 * 1000 || !d.ok);
  });
}

/** The freshness line a list page shows: the price source, then the dataset line when there is one. */
export function freshnessLine(datasetLine: string | null | undefined): string {
  return `${PRICE_FRESHNESS} · ${datasetLine ?? "Research data refreshed nightly"}`;
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

/**
 * Build a Trade's price line: the spot the options were priced at, dated by the chain, and the stock now,
 * dated by its own last trade. Never a request-time stamp.
 * "priced at $339.85 from the 2026-09-28 options data; the stock is now $332.35 (last trade 09:31:00)"
 */
export function pricedAtLine(
  fb: { current_price: number; options_as_of?: string | null; quote_price?: number | null; price_as_of?: string | null },
  fmtTime: (iso: string | null | undefined) => string | null,
): string {
  const source = fb.options_as_of ? `from the ${fb.options_as_of} options data` : "from the latest stored options data";
  const head = `priced at $${fb.current_price.toFixed(2)} ${source}`;
  if (fb.quote_price == null) return head;
  const t = fmtTime(fb.price_as_of);
  return `${head}; the stock is now $${fb.quote_price.toFixed(2)}${t ? ` (last trade ${t})` : ""}`;
}

/**
 * The window an implied move covers, from the data: "through 2026-11-20, 52 days from the 2026-09-28 options data".
 * The move is priced to expiry, so it is never compared with one-day history.
 */
export function impliedSpanPhrase(expiration: string | null | undefined, spanDays: number | null | undefined, chainDate: string | null | undefined): string | null {
  if (!expiration) return null;
  if (spanDays == null || !chainDate) return `through ${expiration}`;
  return `through ${expiration}, ${spanDays} ${spanDays === 1 ? "day" : "days"} from the ${chainDate} options data`;
}

/** "One-day earnings moves: avg ±5.2%, max ±11.0% over 12 prints" (a 0-1 decimal in, like the API). */
export function oneDayHistoryLine(hist: { avg_abs_move_pct: number; max_abs_move_pct: number; sample_size: number } | null | undefined): string | null {
  if (!hist || hist.sample_size < 3) return null;
  return `One-day earnings moves: avg ±${(hist.avg_abs_move_pct * 100).toFixed(1)}%, max ±${(hist.max_abs_move_pct * 100).toFixed(1)}% over ${hist.sample_size} prints`;
}
