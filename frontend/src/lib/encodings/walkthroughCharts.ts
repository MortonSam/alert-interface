// The walkthrough's two charts (step 4, the stock against the market; step 5, what investors pay for each $1 of profit against its
// own history, in dollars, Sam 2026-11-04). Each chart
// and its legend read these configs; a label with {name}, {sector} or {median} takes the stock's own from the API. The median's
// name is the API's (chart.median_label): "Its five-year median" only when five full years are counted, otherwise "Its median
// since Oct 20, 2023" (Sam, 2026-11-10).
import type { LegendItem } from "./types";

export const PRICE_VS_MARKET_ENCODING = {
  stock:  { label: "{name}",                color: "hsl(var(--primary))",          dash: "",    width: 2.5, opacity: 1 },
  spy:    { label: "S&P 500 (SPY)",         color: "hsl(var(--foreground))",       dash: "6 4", width: 1.5, opacity: 0.75 },
  sector: { label: "Median {sector} stock", color: "hsl(var(--cool))",             dash: "2 3", width: 1.5, opacity: 0.9 },
  base:   { label: "Where each line started (100)", color: "hsl(var(--border))",   dash: "",    width: 1,   opacity: 1 },
} as const;

export const PE_RANGE_ENCODING = {
  pe:           { label: "Paid for each $1 of profit, each trading day", color: "hsl(var(--primary))", dash: "", width: 2, opacity: 1 },
  median:       { label: "{median}",                  color: "hsl(var(--foreground))", dash: "6 4", width: 1.5, opacity: 0.75 },
  sectorMedian: { label: "Median {sector} stock now", color: "hsl(var(--cool))",       dash: "2 3", width: 1.5, opacity: 0.9 },
  today:        { label: "Today",                     color: "hsl(var(--primary))",    dash: "",    width: 0,   opacity: 1, dot: true },
} as const;

export type PriceMarkKey = keyof typeof PRICE_VS_MARKET_ENCODING;
export type PeMarkKey = keyof typeof PE_RANGE_ENCODING;

function fill(label: string, vars: { name?: string; sector?: string | null; median?: string }) {
  return label.replace("{name}", vars.name ?? "").replace("{sector}", vars.sector ?? "").replace("{median}", vars.median ?? "Its median");
}

/** Recharts stroke props for a mark. */
export function priceMark(key: PriceMarkKey) {
  const m = PRICE_VS_MARKET_ENCODING[key];
  return { stroke: m.color, strokeWidth: m.width, strokeDasharray: m.dash || undefined, strokeOpacity: m.opacity };
}

export function peMark(key: PeMarkKey) {
  const m = PE_RANGE_ENCODING[key];
  return { stroke: m.color, strokeWidth: m.width, strokeDasharray: m.dash || undefined, strokeOpacity: m.opacity };
}

/** Legend rows for the marks a chart actually draws (the sector line only when the API sent one). */
export function priceVsMarketLegend(keys: PriceMarkKey[], vars: { name: string; sector: string | null }): LegendItem[] {
  return keys.map((key) => {
    const m = PRICE_VS_MARKET_ENCODING[key];
    return { key, label: fill(m.label, vars), swatch: { kind: "line" as const, color: m.color, dashed: m.dash !== "", opacity: m.opacity } };
  });
}

export function peRangeLegend(keys: PeMarkKey[], vars: { sector: string | null; median?: string }): LegendItem[] {
  return keys.map((key) => {
    const m = PE_RANGE_ENCODING[key];
    return { key, label: fill(m.label, vars), swatch: "dot" in m ? { kind: "dot" as const, color: m.color } : { kind: "line" as const, color: m.color, dashed: m.dash !== "", opacity: m.opacity } };
  });
}
