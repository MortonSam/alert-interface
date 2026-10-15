// Earnings markers on the price chart: a dashed vertical line per report,
// colored by EPS outcome (not by direction; the reaction bars below use direction). Green and red mean up and down alone
// (DESIGN.md), so a beat is blue and a miss amber.
import type { EarningsOutcome } from "@/lib/api";
import type { LegendItem } from "./types";

export const EARNINGS_MARKER_ENCODING = {
  beat:    { label: "EPS beat",        color: "#38bdf8" },
  miss:    { label: "EPS miss",        color: "#f59e0b" },
  meet:    { label: "EPS met",         color: "#9ca3af" },
  unknown: { label: "no EPS data",     color: "#9ca3af" },
  no_reported_figure: { label: "no EPS data", color: "#9ca3af" },   // the same mark as unknown: a report with no figure to judge it by
} as const satisfies Record<EarningsOutcome, { label: string; color: string }>;

export const EARNINGS_MARKER_DASH = "3 3";

export function earningsMarkerColor(outcome: EarningsOutcome | string): string {
  return (EARNINGS_MARKER_ENCODING as Record<string, { color: string }>)[outcome]?.color ?? EARNINGS_MARKER_ENCODING.unknown.color;
}

/** One swatch per distinct look: meet and unknown share gray, so they share an entry. */
export function earningsMarkerLegend(): LegendItem[] {
  const byColor = new Map<string, string[]>();
  for (const [, v] of Object.entries(EARNINGS_MARKER_ENCODING)) {
    const labels = byColor.get(v.color) ?? [];
    if (!labels.includes(v.label)) labels.push(v.label);          // "no EPS data" once, though two outcomes carry it
    byColor.set(v.color, labels);
  }
  return [...byColor.entries()].map(([color, labels]) => ({
    key: color, label: labels.join(" / "), swatch: { kind: "line", color, dashed: true },
  }));
}
