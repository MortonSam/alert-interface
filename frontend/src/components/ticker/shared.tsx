/**
 * Shared types, constants, and utilities for ticker page components.
 */
import { type StrategyData, type StrikeData } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

export type StrategyType = "long_call" | "long_put" | "covered_call" | "csp";
export type MultiLegType = "bear_call_spread" | "short_strangle" | "iron_condor";
export type Outlook = "bullish" | "bearish" | "neutral";

export interface StrategyMeta {
  name: string;
  oneLiner: string;
  description: string;
  usesCall: boolean;
}

export interface MultiLegMeta {
  name: string;
  oneLiner: string;
  description: string;
}

export interface StrategyStats {
  maxGain: number | null;
  maxLoss: number;
  breakevens: number[];
}

export interface MultiLegStats {
  netCredit: number;
  maxGain: number;
  maxLoss: number | null;
  breakevens: number[];
}

// ── Constants ────────────────────────────────────────────────────────────────

export const TIPS = {
  iv: "Implied Volatility — the market's forecast of how much this stock will move, stated as an annualized %. Higher IV = bigger expected swings = pricier options.",
  atm: "At-The-Money — the strike price closest to where the stock is currently trading. The expected move is anchored here.",
  straddle: "A straddle is buying both an ATM call and an ATM put. Its total cost equals the market's best guess at the stock's move in either direction.",
  impliedRange: "The price range the market thinks the stock will stay within by expiration, derived from options pricing. About 68% of outcomes are expected to fall inside this band.",
  impliedMove: "Derived from the ATM straddle price divided by the stock price. It's what options traders collectively expect the stock to move — in either direction — by expiration.",
  bid: "The highest price a buyer is currently willing to pay for this option contract.",
  ask: "The lowest price a seller will accept. The fair value is usually near the midpoint between bid and ask.",
  openInterest: "The total number of open option contracts at this strike that haven't been closed or exercised. High open interest means more market participation.",
  strike: "The fixed price at which the option lets you buy (call) or sell (put) the stock, regardless of where the stock actually trades.",
} as const;

export const STRATEGY_META: Record<StrategyType, StrategyMeta> = {
  long_call: {
    name: "Long Call",
    oneLiner: "Bullish — pay a premium for the right to buy shares at the strike.",
    description:
      "A long call profits when the stock rises above your breakeven by expiration. " +
      "Risk is capped at the premium paid — no matter how far the stock falls, that's " +
      "the most you can lose. Upside is theoretically unlimited as the stock moves higher.",
    usesCall: true,
  },
  long_put: {
    name: "Long Put",
    oneLiner: "Bearish — pay a premium for the right to sell shares at the strike.",
    description:
      "A long put profits when the stock falls below your breakeven. Risk is limited " +
      "to the premium paid. Maximum gain is the strike minus the premium (approached " +
      "as the stock nears zero). A defined-risk way to express a bearish view.",
    usesCall: false,
  },
  covered_call: {
    name: "Covered Call",
    oneLiner: "Mildly bullish or neutral — sell a call against 100 shares you already own.",
    description:
      "You own 100 shares and sell a call at the chosen strike, collecting the premium " +
      "immediately. If the stock stays below the strike at expiration you keep both the " +
      "shares and the premium, reducing your effective cost basis. If it rises above, " +
      "your shares get called away at the strike — capping your upside.",
    usesCall: true,
  },
  csp: {
    name: "Cash-Secured Put",
    oneLiner: "Neutral to bullish — sell a put with cash set aside to buy shares if assigned.",
    description:
      "You sell a put and hold enough cash to buy 100 shares if the stock falls to the " +
      "strike. If it stays above, you keep the premium — your maximum gain. If it falls " +
      "below, you effectively buy the stock at (strike − premium), often below today's price. " +
      "Generates income while expressing willingness to own the stock at a lower price.",
    usesCall: false,
  },
};

export const MULTI_LEG_META: Record<MultiLegType, MultiLegMeta> = {
  bear_call_spread: {
    name: "Bear Call Spread",
    oneLiner: "Bearish — sell an OTM call, buy a higher-strike call to cap risk.",
    description:
      "You sell a call at the short strike and buy a higher call (the wing) to limit upside risk. " +
      "You collect a net credit upfront. If the stock stays below the short strike at expiration, " +
      "both calls expire worthless and you keep the full credit. If it rises above the long strike, " +
      "you lose the wing width minus the credit. A defined-risk bearish trade.",
  },
  short_strangle: {
    name: "Short Strangle",
    oneLiner: "Neutral — sell an OTM call and OTM put, profit if the stock stays between the short strikes.",
    description:
      "You simultaneously sell an out-of-the-money call and put, collecting both premiums. " +
      "Max gain is the combined credit if the stock expires between the two short strikes. " +
      "Losses are unlimited in either direction — the call side has no cap, and the put side grows " +
      "as the stock falls toward zero. Thrives in high-IV environments but requires active management.",
  },
  iron_condor: {
    name: "Iron Condor",
    oneLiner: "Neutral — a short strangle with protective wings on both sides for fully defined risk.",
    description:
      "A short call spread plus a short put spread. You collect a net credit and profit if the stock " +
      "stays between the short strikes at expiration. The wings (long options) cap your maximum loss at " +
      "wing width minus the credit. Less premium than a naked strangle, but risk is fully defined.",
  },
};

export const OUTLOOK_STRATEGIES: Record<Outlook, (StrategyType | MultiLegType)[]> = {
  bullish: ["long_call", "covered_call", "csp"],
  bearish: ["long_put", "bear_call_spread"],
  neutral: ["short_strangle", "iron_condor"],
};

// ── Utility functions ────────────────────────────────────────────────────────

export function fmtPctDecimal(v: number | null, digits = 1): string {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export function isMultiLeg(s: StrategyType | MultiLegType): s is MultiLegType {
  return s === "bear_call_spread" || s === "short_strangle" || s === "iron_condor";
}

export function payoffPS(
  strategy: StrategyType,
  K: number,
  premium: number,
  currentPrice: number,
  S: number,
): number {
  switch (strategy) {
    case "long_call":    return Math.max(0, S - K) - premium;
    case "long_put":     return Math.max(0, K - S) - premium;
    case "covered_call": return (S - currentPrice) + premium - Math.max(0, S - K);
    case "csp":          return premium - Math.max(0, K - S);
  }
}

export function strategyStats(
  strategy: StrategyType,
  K: number,
  premium: number,
  currentPrice: number,
): StrategyStats {
  switch (strategy) {
    case "long_call":
      return { maxGain: null, maxLoss: premium, breakevens: [K + premium] };
    case "long_put":
      return { maxGain: K - premium, maxLoss: premium, breakevens: [K - premium] };
    case "covered_call":
      return {
        maxGain: K - currentPrice + premium,
        maxLoss: currentPrice - premium,
        breakevens: [currentPrice - premium],
      };
    case "csp":
      return {
        maxGain: premium,
        maxLoss: K - premium,
        breakevens: [K - premium],
      };
  }
}

export function payoffBSPS(
  strategy: StrategyType,
  K: number, premium: number, currentPrice: number, S: number,
  T: number, sigma: number, r: number,
  blackScholes: (kind: "call" | "put", S: number, K: number, T: number, sigma: number, r: number) => number,
): number {
  if (T <= 0) return payoffPS(strategy, K, premium, currentPrice, S);
  const bsC = blackScholes("call", S, K, T, sigma, r);
  const bsP = blackScholes("put",  S, K, T, sigma, r);
  switch (strategy) {
    case "long_call":    return bsC - premium;
    case "long_put":     return bsP - premium;
    case "covered_call": return (S - currentPrice) + premium - bsC;
    case "csp":          return premium - bsP;
  }
}

// Custom Y-axis tick: signed (+/−), color-coded green/red
export function PayoffYTick({
  x, y, payload,
}: {
  x?: number;
  y?: number;
  payload?: { value: number };
}) {
  if (x == null || y == null || !payload) return null;
  const v = payload.value;
  const color = v < 0 ? "hsl(var(--destructive))" : v > 0 ? "hsl(var(--success))" : "hsl(var(--muted-foreground))";
  const abs = Math.abs(Math.round(v)).toLocaleString("en-US");
  const label = v >= 0 ? `+$${abs}` : `-$${abs}`;
  return (
    <text x={x} y={y} fill={color} fontSize={10} textAnchor="end" dominantBaseline="middle">
      {label}
    </text>
  );
}
