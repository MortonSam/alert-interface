// How close the next earnings report is. One scale for discover and the watchlist.
import type { LegendItem } from "./types";

export const EARNINGS_PROXIMITY_ENCODING = {
  imminent: { maxDays: 1,        label: "today or tomorrow", className: "bg-primary/10 text-primary" },
  soon:     { maxDays: 3,        label: "within 3 days",     className: "bg-warning/10 text-warning" },
  later:    { maxDays: Infinity, label: "further out",       className: "bg-muted text-muted-foreground" },
} as const;

export type EarningsProximityKey = keyof typeof EARNINGS_PROXIMITY_ENCODING;

/** days = whole days until the report; negative means it already happened (no tag). */
export function earningsProximity(days: number) {
  if (days < 0) return null;
  const key: EarningsProximityKey = days <= EARNINGS_PROXIMITY_ENCODING.imminent.maxDays ? "imminent"
    : days <= EARNINGS_PROXIMITY_ENCODING.soon.maxDays ? "soon" : "later";
  return { key, ...EARNINGS_PROXIMITY_ENCODING[key] };
}

export function earningsProximityText(days: number): string {
  return days === 0 ? "EPS today" : days === 1 ? "EPS tomorrow" : `EPS in ${days}d`;
}

export function earningsProximityLegend(): LegendItem[] {
  return (Object.keys(EARNINGS_PROXIMITY_ENCODING) as EarningsProximityKey[]).map((key) => ({
    key, label: `Reports ${EARNINGS_PROXIMITY_ENCODING[key].label}`,
    swatch: { kind: "pill", className: EARNINGS_PROXIMITY_ENCODING[key].className },
  }));
}
