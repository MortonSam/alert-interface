// The Meet Ivy evidence chart: for each backtest year, how often the stock was higher five days later after her setups, against
// all earnings reports that year. One dot each, on one percent scale.
import type { LegendItem } from "./types";

export const IVY_BACKTEST_ENCODING = {
  setups: { label: "Her setups", color: "hsl(29 100% 55%)", filled: true },
  base:   { label: "All earnings reports", color: "hsl(240 5% 65%)", filled: false },
} as const;

export function ivyBacktestLegend(): LegendItem[] {
  return (Object.keys(IVY_BACKTEST_ENCODING) as (keyof typeof IVY_BACKTEST_ENCODING)[]).map((key) => ({
    key, label: IVY_BACKTEST_ENCODING[key].label,
    swatch: { kind: "dot" as const, color: IVY_BACKTEST_ENCODING[key].color, hollow: !IVY_BACKTEST_ENCODING[key].filled },
  }));
}

/** The chart's percent scale: whole points around every rate shown, so the gap is read against labelled ticks. */
export function backtestScale(rates: number[]): { min: number; max: number } {
  const pts = rates.map((r) => r * 100);
  return { min: Math.floor(Math.min(...pts) - 1), max: Math.ceil(Math.max(...pts) + 1) };
}
