// IV versus realized volatility regime chip (discover cards, Build a Trade, My Trades).
// "Cheap" is not "good": the chip uses a neutral cool color, never the up/beat green.
import { DISCOVER_IV_CHEAP_PP, DISCOVER_IV_RICH_PP } from "@/lib/thresholds";
import type { LegendItem } from "./types";

export const VOL_REGIME_ENCODING = {
  iv_rich:  { label: "IV Rich",  className: "bg-warning/10 text-warning",
              rule: `options price in ${DISCOVER_IV_RICH_PP}+ points more volatility than the stock recently delivered` },
  iv_cheap: { label: "IV Cheap", className: "bg-cool/10 text-cool",
              rule: `options price in ${Math.abs(DISCOVER_IV_CHEAP_PP)}+ points less volatility than the stock recently delivered` },
  iv_fair:  { label: "IV Fair",  className: "bg-muted text-muted-foreground",
              rule: `implied and realized volatility are within ${Math.abs(DISCOVER_IV_CHEAP_PP)} points below to ${DISCOVER_IV_RICH_PP} points above` },
} as const;

export type VolRegimeKey = keyof typeof VOL_REGIME_ENCODING;

export function volRegime(key: string | null | undefined) {
  return key && key in VOL_REGIME_ENCODING ? { key: key as VolRegimeKey, ...VOL_REGIME_ENCODING[key as VolRegimeKey] } : null;
}

export function volRegimeLegend(): LegendItem[] {
  return (Object.keys(VOL_REGIME_ENCODING) as VolRegimeKey[]).map((key) => ({
    key, label: `${VOL_REGIME_ENCODING[key].label}: ${VOL_REGIME_ENCODING[key].rule}`,
    swatch: { kind: "pill", className: VOL_REGIME_ENCODING[key].className },
  }));
}
