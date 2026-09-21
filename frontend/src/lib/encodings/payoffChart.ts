// The payoff simulator's marks. The chart and its legend both read this.
import type { LegendItem } from "./types";

export const PAYOFF_CHART_ENCODING = {
  profit:   { label: "Simulated profit at that stock price", color: "hsl(var(--success))",          dash: "",    width: 2.5, opacity: 1 },
  loss:     { label: "Simulated loss at that stock price",   color: "hsl(var(--destructive))",      dash: "",    width: 2.5, opacity: 1 },
  current:  { label: "Stock price when this was priced",     color: "hsl(var(--muted-foreground))", dash: "3 5", width: 1,   opacity: 0.6 },
  scrubber: { label: "The stock price you are inspecting",   color: "hsl(var(--cool))",             dash: "",    width: 1.5, opacity: 0.7 },
  zero:     { label: "$0: no gain or loss",                  color: "hsl(var(--border))",           dash: "",    width: 1,   opacity: 1 },
} as const;

export type PayoffMarkKey = keyof typeof PAYOFF_CHART_ENCODING;

/** Recharts stroke props for a mark. */
export function payoffMark(key: PayoffMarkKey) {
  const m = PAYOFF_CHART_ENCODING[key];
  return { stroke: m.color, strokeWidth: m.width, strokeDasharray: m.dash || undefined, strokeOpacity: m.opacity };
}

export function payoffChartLegend(): LegendItem[] {
  return (Object.keys(PAYOFF_CHART_ENCODING) as PayoffMarkKey[]).map((key) => ({
    key, label: PAYOFF_CHART_ENCODING[key].label,
    swatch: { kind: "line", color: PAYOFF_CHART_ENCODING[key].color, dashed: PAYOFF_CHART_ENCODING[key].dash !== "", opacity: PAYOFF_CHART_ENCODING[key].opacity },
  }));
}
