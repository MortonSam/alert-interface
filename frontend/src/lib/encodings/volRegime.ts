// IV versus realized volatility regime chip (discover cards, Build a Trade, My Trades).
// "Cheap" is not "good": the chip uses a neutral cool color, never the up/beat green.
import { DISCOVER_IV_CHEAP_PP, DISCOVER_IV_RICH_PP } from "@/lib/thresholds";
import type { LegendItem } from "./types";

// Each rule is one plain sentence with one example, comparing two yearly figures and never in "points" (Sam, 2026-11-11). The
// example is worked from the cutoffs: the regime is rich above EXAMPLE_RV + RICH and cheap below EXAMPLE_RV - CHEAP.
const EXAMPLE_RV = 30;
const RICH = DISCOVER_IV_RICH_PP, CHEAP = Math.abs(DISCOVER_IV_CHEAP_PP);
const SHOWN = `a year where the stock has shown ${EXAMPLE_RV}%, for example.`;

export const VOL_REGIME_ENCODING = {
  iv_rich:  { label: "IV Rich",  className: "bg-warning/10 text-warning",
              rule: `Options expect more swing than the stock has shown lately: over ${EXAMPLE_RV + RICH}% ${SHOWN}` },
  iv_cheap: { label: "IV Cheap", className: "bg-cool/10 text-cool",
              rule: `Options expect less swing than the stock has shown lately: under ${EXAMPLE_RV - CHEAP}% ${SHOWN}` },
  iv_fair:  { label: "IV Fair",  className: "bg-muted text-muted-foreground",
              rule: `Options expect about the swing the stock has shown lately: from ${EXAMPLE_RV - CHEAP}% to ${EXAMPLE_RV + RICH}% ${SHOWN}` },
} as const;

export type VolRegimeKey = keyof typeof VOL_REGIME_ENCODING;

export function volRegime(key: string | null | undefined) {
  return key && key in VOL_REGIME_ENCODING ? { key: key as VolRegimeKey, ...VOL_REGIME_ENCODING[key as VolRegimeKey] } : null;
}

export function volRegimeLegend(): LegendItem[] {
  return (Object.keys(VOL_REGIME_ENCODING) as VolRegimeKey[]).map((key) => ({
    key, label: `${VOL_REGIME_ENCODING[key].label}: ${VOL_REGIME_ENCODING[key].rule.replace(/^O/, "o")}`,
    swatch: { kind: "pill", className: VOL_REGIME_ENCODING[key].className },
  }));
}
