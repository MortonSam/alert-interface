import type { EarningsOutcome } from "@/lib/api";

// Single source of truth for what the reaction bars encode.
// Both the bar <Cell> props and the legend are derived from this object.
export const REACTION_CHART_ENCODING = {
  direction: {
    up: { label: "Up", color: "#22c55e" },
    down: { label: "Down", color: "#ef4444" },
  },
  outcome: {
    beat: { label: "Beat", description: "solid", fillOpacity: 1.0, dashed: false },
    miss: { label: "Miss", description: "dashed outline", fillOpacity: 0.7, dashed: true },
    meet: { label: "Meet / no EPS data", description: "faded", fillOpacity: 0.5, dashed: false },
  },
  // Which outcome style each API outcome value renders with.
  outcomeStyleFor: {
    beat: "beat",
    miss: "miss",
    meet: "meet",
    unknown: "meet",
  } satisfies Record<EarningsOutcome, "beat" | "miss" | "meet">,
  noData: { fill: "hsl(var(--muted))", stroke: "hsl(var(--muted-foreground))", fillOpacity: 0.3 },
  missStrokeWidth: 1.5,
  missDash: "3 2",
} as const;

export type DirectionKey = keyof typeof REACTION_CHART_ENCODING.direction;
export type OutcomeStyleKey = keyof typeof REACTION_CHART_ENCODING.outcome;

export interface BarCellStyle {
  fill: string;
  fillOpacity: number;
  stroke: string;
  strokeWidth: number;
  strokeDasharray: string;
  directionKey: DirectionKey | null;
  outcomeKey: OutcomeStyleKey | null;
}

export function barCellStyle(
  pct1d: number | null,
  outcome: EarningsOutcome,
  isFed: boolean,
): BarCellStyle {
  const enc = REACTION_CHART_ENCODING;
  if (pct1d == null) {
    return {
      fill: enc.noData.fill, fillOpacity: enc.noData.fillOpacity,
      stroke: enc.noData.stroke, strokeWidth: 1, strokeDasharray: "2 2",
      directionKey: null, outcomeKey: null,
    };
  }
  const directionKey: DirectionKey = pct1d >= 0 ? "up" : "down";
  const color = enc.direction[directionKey].color;
  if (isFed) {
    return {
      fill: color, fillOpacity: 1.0, stroke: "none", strokeWidth: 0, strokeDasharray: "",
      directionKey, outcomeKey: null,
    };
  }
  const outcomeKey: OutcomeStyleKey = enc.outcomeStyleFor[outcome] ?? "meet";
  const o = enc.outcome[outcomeKey];
  return {
    fill: color,
    fillOpacity: o.fillOpacity,
    stroke: o.dashed ? color : "none",
    strokeWidth: o.dashed ? enc.missStrokeWidth : 0,
    strokeDasharray: o.dashed ? enc.missDash : "",
    directionKey,
    outcomeKey,
  };
}

export type LegendEntry =
  | { kind: "direction"; key: DirectionKey; label: string; color: string }
  | { kind: "outcome"; key: OutcomeStyleKey; label: string; fillOpacity: number; dashed: boolean };

export function legendEntries(isFed: boolean): LegendEntry[] {
  const enc = REACTION_CHART_ENCODING;
  const entries: LegendEntry[] = (Object.keys(enc.direction) as DirectionKey[]).map((key) => ({
    kind: "direction", key, label: enc.direction[key].label, color: enc.direction[key].color,
  }));
  if (!isFed) {
    for (const key of Object.keys(enc.outcome) as OutcomeStyleKey[]) {
      const o = enc.outcome[key];
      entries.push({
        kind: "outcome", key, label: `${o.label} (${o.description})`,
        fillOpacity: o.fillOpacity, dashed: o.dashed,
      });
    }
  }
  return entries;
}
