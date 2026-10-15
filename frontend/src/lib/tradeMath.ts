import { normCDF } from "@/lib/black-scholes";

/**
 * Build a Trade's figures for a debit trade (a long call or put, or a bull call or bear put spread), per contract of 100 shares
 * (2026-10-15). Every input comes from the draft's options data: the strikes and mids it priced, the chain's spot, the at-the-money
 * implied volatility and the implied move for the expiration used.
 *
 *  expiryPnl            profit or loss at expiration at a stock price: intrinsic value less the cost (a spread's value is capped at its width)
 *  breakevenPrice       the long strike plus the cost (a call) or less it (a put)
 *  gainAtImpliedMove    the profit or loss at expiration if the stock moves by the implied move in the trade's direction
 *  chancePastBreakeven  the chance the stock finishes past breakeven at expiration under a lognormal model at the at-the-money implied
 *                       volatility with no drift (the median price is today's): an estimate from option prices, not a forecast
 *  breakevenStretch     the move breakeven needs, as a share of the implied move; past BREAKEVEN_STRETCH_FLAG the draft says so
 */
export const BREAKEVEN_STRETCH_FLAG = 1.5;
export const DAYS_PER_YEAR = 365;

export interface DebitTrade {
  direction: "bullish" | "bearish";
  strike: number;               // the long leg
  spreadStrike: number | null;  // the short leg of a spread, else null
  costPerShare: number;         // the premium paid (a spread's net debit), per share
}

function width(t: DebitTrade): number | null {
  return t.spreadStrike == null ? null : Math.abs(t.spreadStrike - t.strike);
}

export function expiryPnl(t: DebitTrade, price: number): number {
  let intrinsic = t.direction === "bullish" ? Math.max(0, price - t.strike) : Math.max(0, t.strike - price);
  const w = width(t);
  if (w != null) intrinsic = Math.min(intrinsic, w);
  return (intrinsic - t.costPerShare) * 100;
}

export function breakevenPrice(t: DebitTrade): number {
  return t.direction === "bullish" ? t.strike + t.costPerShare : t.strike - t.costPerShare;
}

export function impliedMovePrice(spot: number, movePct: number, direction: DebitTrade["direction"]): number {
  return spot * (1 + (direction === "bullish" ? 1 : -1) * movePct / 100);
}

export function gainAtImpliedMove(t: DebitTrade, spot: number, movePct: number): number {
  return expiryPnl(t, impliedMovePrice(spot, movePct, t.direction));
}

export function chancePastBreakeven(spot: number, breakeven: number, ivPct: number, days: number, direction: DebitTrade["direction"]): number | null {
  if (!(spot > 0 && breakeven > 0 && ivPct > 0 && days > 0)) return null;
  const sigma = ivPct / 100;
  const t = days / DAYS_PER_YEAR;
  const sd = sigma * Math.sqrt(t);
  const z = (Math.log(breakeven / spot) + 0.5 * sigma * sigma * t) / sd;    // ln S_T ~ N(ln S - sigma^2 t / 2, sigma^2 t)
  const above = 1 - normCDF(z);
  return direction === "bullish" ? above : 1 - above;
}

export function breakevenStretch(spot: number, breakeven: number, movePct: number): { requiredPct: number; ratio: number } | null {
  if (!(spot > 0 && movePct > 0)) return null;
  const requiredPct = Math.abs(breakeven / spot - 1) * 100;
  return { requiredPct, ratio: requiredPct / movePct };
}

// ── words ────────────────────────────────────────────────────────────────────

export function fmtDollars(v: number): string {
  const s = `$${Math.round(Math.abs(v)).toLocaleString("en-US")}`;
  return v < 0 ? `\u2212${s}` : `+${s}`;
}

/** The flag under a draft whose breakeven asks for more than BREAKEVEN_STRETCH_FLAG times the implied move; null otherwise. */
export function stretchLine(spot: number, breakeven: number, movePct: number): string | null {
  const s = breakevenStretch(spot, breakeven, movePct);
  if (!s || s.ratio <= BREAKEVEN_STRETCH_FLAG) return null;
  const times = s.ratio.toFixed(1) === BREAKEVEN_STRETCH_FLAG.toFixed(1) ? s.ratio.toFixed(2) : s.ratio.toFixed(1);   // never "1.5 times" for a flag past 1.5
  return `Breakeven needs a ${s.requiredPct.toFixed(1)}% move, ${times} times the ${movePct.toFixed(1)}% the options imply.`;
}

/** The receipt under the two figures: what the estimate used. */
export function estimateReceipt(ivPct: number, days: number, spot: number, chainDate: string | null | undefined): string {
  return `At-the-money implied volatility ${ivPct.toFixed(1)}%, ${days} days to expiration, stock at $${spot.toFixed(2)}${chainDate ? ` in the ${chainDate} options data` : ""}.`;
}

export const ESTIMATE_NOTE = "An estimate from option prices, not a forecast.";

/** The payoff chart's scrub: the stock price under a finger or pointer at `x` pixels across a chart `width` wide whose plot spans
 *  [plotLeft, width - plotRight] and the prices [xMin, xMax]; clamped to the plot. */
export function priceAtX(x: number, width: number, plotLeft: number, plotRight: number, xMin: number, xMax: number): number {
  const span = Math.max(1, width - plotLeft - plotRight);
  const frac = Math.min(1, Math.max(0, (x - plotLeft) / span));
  return xMin + frac * (xMax - xMin);
}

/** The payoff chart's price range: the implied range, widened to take in the strikes and breakeven with PAYOFF_RANGE_PAD either side,
 *  so the scrub can reach where the trade starts to pay. */
export const PAYOFF_RANGE_PAD = 0.03;
export function payoffRange(impliedLow: number | null, impliedHigh: number | null, spot: number, marks: number[]): [number, number] {
  const lo = Math.min(impliedLow ?? spot * 0.8, ...marks.map((m) => m * (1 - PAYOFF_RANGE_PAD)));
  const hi = Math.max(impliedHigh ?? spot * 1.2, ...marks.map((m) => m * (1 + PAYOFF_RANGE_PAD)));
  return [lo, hi];
}
