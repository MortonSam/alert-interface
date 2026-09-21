// While Ivy's Read is shown, the rows beside it render from the fact block the
// read was generated from, so a number in the prose and a number in a row can
// never disagree. Without a read, the rows render from the live endpoints.

import type { ExpectedMove, OptionsRead, RealizedVol } from "@/lib/api";

export const READ_PRICE_DRIFT_PCT = 1;   // note the read's price when the quote has moved more than this

export interface OptionFactValues {
  current_price: number | null;
  price_as_of: string | null;
  chain_date: string | null;
  expected_move_pct: number | null;
  expected_move_dollars: number | null;
  implied_range_low: number | null;
  implied_range_high: number | null;
  expiration_used: string | null;
  atm_strike: number | null;
  atm_iv: number | null;
  atm_iv_as_of: string | null;
  rv_20d: number | null;
  rv_rank: number | null;
  iv_rv_spread_pp: number | null;
  avg_earnings_1d_move_pct?: number | null;
  earnings_sample_size?: number | null;
}

export interface DisplayedOptionFacts extends OptionFactValues {
  source: "read" | "live";
}

export function readIsShown(read: OptionsRead | null | undefined): read is OptionsRead & { fact_values: OptionFactValues } {
  return !!read && read.available !== false && read.model_used !== "none" && !!read.fact_values;
}

/** What the expected-move block and the IV/RV/spread rows render. One source at a time. */
export function displayedOptionFacts(
  read: OptionsRead | null | undefined,
  expectedMove: ExpectedMove | null | undefined,
  realizedVol: RealizedVol | null | undefined,
): DisplayedOptionFacts {
  if (readIsShown(read)) {
    const v = read.fact_values as OptionFactValues;
    return { source: "read", ...v };
  }
  return {
    source: "live",
    current_price: expectedMove?.current_price ?? null,
    price_as_of: null,
    chain_date: null,
    expected_move_pct: expectedMove?.expected_move_pct ?? null,
    expected_move_dollars: expectedMove?.expected_move_dollars ?? null,
    implied_range_low: expectedMove?.implied_range_low ?? null,
    implied_range_high: expectedMove?.implied_range_high ?? null,
    expiration_used: expectedMove?.expiration_used ?? null,
    atm_strike: expectedMove?.atm_strike ?? null,
    atm_iv: realizedVol?.atm_iv ?? null,
    atm_iv_as_of: realizedVol?.atm_iv_as_of ?? null,
    rv_20d: realizedVol?.current_rv ?? null,
    rv_rank: realizedVol?.rv_rank ?? null,
    iv_rv_spread_pp: realizedVol?.iv_rv_spread_pp ?? null,
  };
}

/** "priced at $339.07, last trade 17:59" for the block's label. */
export function priceLabel(f: DisplayedOptionFacts, fmtTime: (iso: string | null) => string | null): string | null {
  if (f.current_price == null) return null;
  const t = fmtTime(f.price_as_of);
  return `priced at $${f.current_price.toFixed(2)}${t ? `, last trade ${t}` : ""}`;
}

/** The one-line note when the quote has moved away from the price the read used. */
export function priceDriftNote(f: DisplayedOptionFacts, quotePrice: number | null | undefined): string | null {
  if (f.source !== "read" || f.current_price == null || quotePrice == null || f.current_price <= 0) return null;
  const drift = Math.abs(quotePrice - f.current_price) / f.current_price * 100;
  if (drift <= READ_PRICE_DRIFT_PCT) return null;
  return `Ivy's Read was written at $${f.current_price.toFixed(2)}; the stock is now $${quotePrice.toFixed(2)} (${drift.toFixed(1)}% away). The figures here are the ones the read used.`;
}
