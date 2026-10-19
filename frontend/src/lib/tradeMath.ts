import { fmtDate } from "@/lib/dates";
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
  const required = s.requiredPct.toFixed(1);
  return `Breakeven needs ${articleFor(required)} ${required}% move, ${times} times the ${movePct.toFixed(1)}% the options imply.`;
}

/** "a" or "an" before a number as it is read aloud: "an" when the reading starts with a vowel sound (eight, eighty, eight hundred,
 *  eleven, eighteen, in the leading group of thousands), "a" otherwise. an 8%, an 11.3%, an 18%, an 80% to 89.9%, a 7.5%, a 1.5%. */
export function articleFor(numText: string): "a" | "an" {
  const int = numText.replace(/^[^0-9]*/, "").split(".")[0].replace(/,/g, "").replace(/^0+(?=\d)/, "");
  if (!int || int === "0") return "a";                                  // "zero point ..."
  const lead = Number(int.slice(0, ((int.length - 1) % 3) + 1));     // the leading group: 11 in 11,300, 8 in 8,000, 850 in 850
  if (lead === 11 || lead === 18) return "an";
  return String(lead).startsWith("8") ? "an" : "a";
}

/** "Oct 14, 2026" from the options data's ISO date (a calendar day, read in UTC so no zone moves it); other text passes through. */
export function fmtChainDate(iso: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? (fmtDate(iso) ?? iso) : iso;
}

/** The label over the gain at the implied move: a call needs the stock to rise, a put needs it to fall. */
export function impliedMoveLabel(symbol: string, direction: "bullish" | "bearish", movePct: number): string {
  return `If ${symbol} ${direction === "bearish" ? "falls" : "rises"} the ${movePct.toFixed(1)}% the options imply by expiration`;
}

export const NO_IMPLIED_MOVE = "Not shown because the options data has no implied move.";
export const NO_IMPLIED_VOL = "Not shown because the options data has no implied volatility.";

/** The receipt under the two figures: what the estimate used. */
export function estimateReceipt(ivPct: number, days: number, spot: number, chainDate: string | null | undefined): string {
  return `At-the-money implied volatility ${ivPct.toFixed(1)}%, ${days} days to expiration, stock at $${spot.toFixed(2)}${chainDate ? ` in the ${fmtChainDate(chainDate)} options data` : ""}.`;
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
