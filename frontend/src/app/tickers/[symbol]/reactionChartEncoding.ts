import type { EarningsOutcome } from "@/lib/api";
import type { LegendItem } from "@/lib/encodings/types";

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

/**
 * Legend rows, as mini-bars. Outcome rows are drawn in the "up" color at the
 * outcome's real opacity and outline, because that is what a bar looks like:
 * a gray dot cannot show "solid vs dashed vs faded".
 */
export function legendEntries(isFed: boolean): LegendItem[] {
  const enc = REACTION_CHART_ENCODING;
  const items: LegendItem[] = (Object.keys(enc.direction) as DirectionKey[]).map((key) => ({
    key: `direction-${key}`,
    label: enc.direction[key].label,
    swatch: { kind: "bar", color: enc.direction[key].color, opacity: 1, dashed: false },
  }));
  if (!isFed) {
    for (const key of Object.keys(enc.outcome) as OutcomeStyleKey[]) {
      const o = enc.outcome[key];
      items.push({
        key: `outcome-${key}`,
        label: `${o.label} (${o.description})`,
        swatch: { kind: "bar", color: enc.direction.up.color, opacity: o.fillOpacity, dashed: o.dashed },
      });
    }
  }
  return items;
}
