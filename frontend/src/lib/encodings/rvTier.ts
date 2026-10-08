// RV rank tier: one function, used by the watchlist, discover and Build a Trade.
// Cutoffs come from lib/thresholds.ts, which a backend test keeps equal to
// backend/app/thresholds.py. Words match the backend's rv_rank_label.
import { RV_RANK_ELEVATED, RV_RANK_EXTREME, RV_RANK_NORMAL } from "@/lib/thresholds";
import type { LegendItem } from "./types";

export const RV_TIER_ENCODING = {
  quiet:    { label: "quiet",    min: 0,                className: "text-muted-foreground", rule: `rank below ${RV_RANK_NORMAL}` },
  normal:   { label: "normal",   min: RV_RANK_NORMAL,   className: "text-muted-foreground", rule: `rank ${RV_RANK_NORMAL} to ${RV_RANK_ELEVATED - 1}` },
  elevated: { label: "elevated", min: RV_RANK_ELEVATED, className: "text-amber-500",        rule: `rank ${RV_RANK_ELEVATED} to ${RV_RANK_EXTREME - 1}` },
  extreme:  { label: "extreme",  min: RV_RANK_EXTREME,  className: "text-primary",          rule: `rank ${RV_RANK_EXTREME} or higher` },
} as const;

export type RvTierKey = keyof typeof RV_TIER_ENCODING;

export function rvTier(rank: number): { key: RvTierKey; label: string; className: string; rule: string } {
  const key: RvTierKey =
    rank >= RV_RANK_EXTREME ? "extreme" : rank >= RV_RANK_ELEVATED ? "elevated" : rank >= RV_RANK_NORMAL ? "normal" : "quiet";
  return { key, ...RV_TIER_ENCODING[key] };
}

export function rvTierLegend(): LegendItem[] {
  return (Object.keys(RV_TIER_ENCODING) as RvTierKey[]).map((key) => ({
    key,
    label: `${RV_TIER_ENCODING[key].label} (${RV_TIER_ENCODING[key].rule})`,
    swatch: { kind: "text", className: RV_TIER_ENCODING[key].className },
  }));
}
