// Earnings markers on the price chart: a dashed vertical line per report, one neutral mark for every report (Block 2, 2026-10-20).
// No outcome is encoded (no estimate is shown anywhere), so a report still settling is the same mark as any other, never "no EPS
// data". The price line keeps its green and red for up and down.
import type { LegendItem } from "./types";

export const EARNINGS_MARKER_ENCODING = {
  report: { label: "Earnings date", color: "#9ca3af" },
} as const;

export const EARNINGS_MARKER_DASH = "3 3";

export function earningsMarkerColor(): string {
  return EARNINGS_MARKER_ENCODING.report.color;
}

/** The legend, from the encoding: one entry, the mark it names. */
export function earningsMarkerLegend(): LegendItem[] {
  return Object.values(EARNINGS_MARKER_ENCODING).map((v) => ({
    key: v.color, label: v.label, swatch: { kind: "line", color: v.color, dashed: true },
  }));
}
