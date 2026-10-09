// Freshness wording, built from the data's own dates and the API's cadence record (backend services/cadence).
// Nothing here types a cadence or a delay: "nightly", "once a day" and the price source come from the record, and
// every quote and chain is named by its own date.
import type { Cadence } from "@/lib/api";

const MARKET_TZ = "America/New_York";

/** "nightly" when the record says one run a day; otherwise the count. Null without a record: callers omit the word. */
export function nightlyWord(cadence: Cadence | null | undefined): string | null {
  if (!cadence) return null;
  return cadence.nightly.per_day === 1 ? "nightly" : `${cadence.nightly.per_day} times a day`;
}

/** "updated once a day" from the options cadence; null without a record. */
export function optionsCadencePhrase(cadence: Cadence | null | undefined): string | null {
  if (!cadence) return null;
  return cadence.options.per_day === 1 ? "updated once a day" : `updated ${cadence.options.per_day} times a day`;
}

/** The price source line: the source named by the record, each quote dated by its own last trade. No delay figure is
 * typed; the record says whether the source states one. */
export function priceSourceLine(cadence: Cadence | null | undefined): string {
  const source = cadence?.quotes.source ?? "the quote source";
  const delay = cadence?.quotes.delay_statement;
  return delay ? `Prices from ${source}, ${delay}` : `Prices from ${source}, each dated by its last trade`;
}

/** A quote's own time, always with its date, on the market clock: "Oct 5, 4:00 PM ET". */
export function fmtQuoteDateTime(unix: number | null | undefined): string | null {
  if (unix == null) return null;
  const d = new Date(unix * 1000);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: MARKET_TZ }) + " ET";
}

/** What a quote's time marks, by the API's quote_basis (backend services/quote_fallback.BASIS_LABELS, mirrored by test):
 * a last trade from the quote source, or the stored session close served when the source had no answer in time. */
export const QUOTE_BASIS_LABELS: Record<"last_trade" | "close", string> = { last_trade: "last trade", close: "close" };
export type QuoteBasis = keyof typeof QUOTE_BASIS_LABELS;

/** A quote's as-of with its date and time, naming a close as a close: "Oct 8, 4:00 PM ET close". */
export function quoteAsOf(unix: number | null | undefined, basis?: QuoteBasis | string | null): string | null {
  const when = fmtQuoteDateTime(unix);
  if (!when) return null;
  return basis === "close" ? `${when} ${QUOTE_BASIS_LABELS.close}` : when;
}

/** An ISO timestamp the same way. */
export function fmtIsoDateTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: MARKET_TZ }) + " ET";
}

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
  return `${label} as of ${ago(oldest.at as string)}` + (failed.length ? ` · last refresh step failed for ${failed.join(", ")}` : "");
}

/** The oldest named dataset is older than `days`: the line turns amber. */
export function datasetsStale(datasets: Record<string, DatasetAgeLike> | null | undefined, keys: string[], days = 3, now = Date.now()): boolean {
  if (!datasets) return false;
  return keys.some((k) => {
    const d = datasets[k];
    return !!d && (!d.at || now - new Date(d.at).getTime() > days * 24 * 60 * 60 * 1000 || !d.ok);
  });
}

/** The freshness line a list page shows: the price source from the cadence record, then the dataset line. Without a
 * dataset line the research clause names the cadence only when the record gives it. */
export function freshnessLine(datasetLine: string | null | undefined, cadence?: Cadence | null): string {
  const word = nightlyWord(cadence);
  const research = datasetLine ?? (word ? `Research data refreshed ${word}` : "Research data from the stored refresh steps");
  return `${priceSourceLine(cadence)} · ${research}`;
}

/** Names the options data by its own date, and its cadence by the record. Never falls back to today. */
export function optionsDataPhrase(chainDate: string | null | undefined, cadence?: Cadence | null): string {
  const cad = optionsCadencePhrase(cadence);
  const base = chainDate ? `options data as of ${chainDate}` : "the latest stored options data";
  return cad ? `${base}, ${cad}` : base;
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
