// Black-Scholes option pricing engine — shared lib
// Extracted from tickers/[symbol]/page.tsx; do not alter logic.

export const BS_R = 0.045;          // risk-free rate (~4.5%; barely moves results at these timeframes)
export const BS_IV_DEFAULT = 0.30;  // fallback IV when per-strike IV is unavailable
export const MS_PER_YEAR = 365.25 * 24 * 3600 * 1000;

export interface Leg {
  kind: "call" | "put";
  K: number;
  mid: number;      // entry premium per share
  sigma: number;    // implied volatility (0–1 decimal) used for pre-expiry BS pricing
  dir: 1 | -1;     // 1 = long, -1 = short
  label: string;
}

/** MS from epoch for a "YYYY-MM-DD" string (midnight local). */
export function dateMs(s: string): number {
  return new Date(s + "T00:00:00").getTime();
}

/** Abramowitz & Stegun 7.1.26 — max error < 1.5e-7. */
export function erfApprox(x: number): number {
  const a1 =  0.254829592, a2 = -0.284496736, a3 = 1.421413741;
  const a4 = -1.453152027, a5 =  1.061405429, p  = 0.3275911;
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + p * ax);
  const y = 1 - (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t) * Math.exp(-ax * ax);
  return sign * y;
}

export function normCDF(x: number): number {
  return 0.5 * (1 + erfApprox(x / Math.SQRT2));
}

/** Black-Scholes option price. T in years, sigma and r as 0–1 decimals. */
export function blackScholes(
  kind: "call" | "put",
  S: number, K: number, T: number, sigma: number, r: number,
): number {
  if (T <= 0 || sigma <= 0) return kind === "call" ? Math.max(0, S - K) : Math.max(0, K - S);
  const sqrtT = Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  return kind === "call"
    ? S * normCDF(d1) - K * Math.exp(-r * T) * normCDF(d2)
    : K * Math.exp(-r * T) * normCDF(-d2) - S * normCDF(-d1);
}

/** Multi-leg payoff at expiration (intrinsic only). Returns per-share P&L. */
export function multiLegPayoffPS(legs: Leg[], S: number): number {
  return legs.reduce((sum, leg) => {
    const intrinsic = leg.kind === "call" ? Math.max(0, S - leg.K) : Math.max(0, leg.K - S);
    return sum + leg.dir * (intrinsic - leg.mid);
  }, 0);
}

/** Multi-leg payoff before expiration using Black-Scholes. Returns per-share P&L. */
export function multiLegPayoffBSPS(legs: Leg[], S: number, T: number, r: number): number {
  if (T <= 0) return multiLegPayoffPS(legs, S);
  return legs.reduce((sum, leg) => {
    const bsPrice = blackScholes(leg.kind, S, leg.K, T, leg.sigma, r);
    return sum + leg.dir * (bsPrice - leg.mid);
  }, 0);
}
