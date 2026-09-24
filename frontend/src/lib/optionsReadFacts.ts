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
  atm_iv_reason?: string | null;   // why atm_iv is null, from iv_store; null when IV is present
  rv_20d: number | null;
  rv_rank: number | null;
  rv_reason?: string | null;     // why rv_20d is null, from rv_store; null when RV is present
  rv_as_of?: string | null;      // snapshot date the RV came from
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
    atm_iv_reason: realizedVol?.atm_iv_reason ?? null,
    rv_20d: realizedVol?.current_rv ?? null,
    rv_reason: realizedVol?.reason ?? null,
    rv_as_of: realizedVol?.as_of ?? null,
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

export const RV_NO_REASON_RECORDED = "Realized volatility is unavailable and no reason was recorded";
export const RV_STILL_LOADING = "Realized volatility is still loading";

/**
 * The sentence under "RV unavailable", from the source the row is showing:
 * the read's stored rv_reason in read mode, the live endpoint's reason in
 * live mode. Never empty: an absent value always carries its reason.
 */
export function rvUnavailableReason(
  shown: DisplayedOptionFacts,
  realizedVol: RealizedVol | null | undefined,
  rvStatus: "loading" | "done" | "empty" | "error" | undefined,
): string {
  if (shown.source === "read") {
    if (shown.rv_reason) return `${shown.rv_reason} (when Ivy's Read was written)`;
    return "Realized volatility was unavailable when Ivy's Read was written";
  }
  if (realizedVol?.reason) return realizedVol.reason;
  if (rvStatus === "loading") return RV_STILL_LOADING;
  if (rvStatus === "error") return "Realized volatility could not be loaded";
  return RV_NO_REASON_RECORDED;
}

/** The sentence under "IV unavailable", from the source the row is showing. Never empty. */
export function ivUnavailableReason(
  shown: DisplayedOptionFacts,
  realizedVol: RealizedVol | null | undefined,
  rvStatus: "loading" | "done" | "empty" | "error" | undefined,
): string {
  if (shown.source === "read") {
    if (shown.atm_iv_reason) return `${shown.atm_iv_reason} (when Ivy's Read was written)`;
    return "Implied volatility was unavailable when Ivy's Read was written";
  }
  if (realizedVol?.atm_iv_reason) return realizedVol.atm_iv_reason;
  if (rvStatus === "loading") return "Implied volatility is still loading";
  if (rvStatus === "error") return "Implied volatility could not be loaded";
  return "Implied volatility is unavailable and no reason was recorded";
}

/**
 * Why the IV-RV spread row has no number: whichever side is missing, with
 * that side's reason, or the consistency check when both are present but the
 * server's spread disagrees with them. Null when the spread can be shown.
 */
export function spreadUnavailableReason(
  shown: DisplayedOptionFacts,
  realizedVol: RealizedVol | null | undefined,
  rvStatus: "loading" | "done" | "empty" | "error" | undefined,
  spreadShown: boolean,
): string | null {
  const ivMissing = shown.atm_iv == null;
  const rvMissing = shown.rv_20d == null;
  if (ivMissing && rvMissing) {
    return `IV-RV spread unavailable: implied and realized volatility are both missing (${ivUnavailableReason(shown, realizedVol, rvStatus)}; ${rvUnavailableReason(shown, realizedVol, rvStatus)})`;
  }
  if (ivMissing) return `IV-RV spread unavailable: implied volatility is missing (${ivUnavailableReason(shown, realizedVol, rvStatus)})`;
  if (rvMissing) return `IV-RV spread unavailable: realized volatility is missing (${rvUnavailableReason(shown, realizedVol, rvStatus)})`;
  if (!spreadShown) return "IV-RV spread unavailable: the stored spread does not match the IV and RV shown";
  return null;
}
