// How a ledger pick's outcome is shown. HIT/MISS is about the stock's direction
// versus entry, not about whether the option made money.
import type { LegendItem } from "./types";

export const PICK_RESULT_ENCODING = {
  hit:  { label: "Direction HIT",  detail: "stock closed the right side of entry", className: "bg-success/10 text-success" },
  miss: { label: "Direction MISS", detail: "stock closed the wrong side of entry", className: "bg-destructive/10 text-destructive" },
} as const;

export const PICK_MOVE_ENCODING = {
  favorable:   { label: "moved in Ivy's favor", className: "text-success" },
  unfavorable: { label: "moved against Ivy",    className: "text-destructive" },
  flat:        { label: "unchanged",            className: "text-muted-foreground" },
} as const;

export function pickResult(directionHit: boolean | null | undefined) {
  if (directionHit == null) return null;
  const key = directionHit ? "hit" : "miss";
  return { key, ...PICK_RESULT_ENCODING[key] };
}

/** Color of the stock move: by whether it went Ivy's way, which differs from its sign on a bearish pick. */
export function pickMove(direction: string, movePct: number) {
  const key = movePct === 0 ? "flat" : (direction === "bullish") === (movePct > 0) ? "favorable" : "unfavorable";
  return { key, ...PICK_MOVE_ENCODING[key] };
}

export function pickResultLegend(): LegendItem[] {
  return [
    ...(Object.keys(PICK_RESULT_ENCODING) as (keyof typeof PICK_RESULT_ENCODING)[]).map((key) => ({
      key, label: `${PICK_RESULT_ENCODING[key].label}: ${PICK_RESULT_ENCODING[key].detail}`,
      swatch: { kind: "pill" as const, className: PICK_RESULT_ENCODING[key].className },
    })),
    ...(["favorable", "unfavorable"] as const).map((key) => ({
      key, label: `Move color: ${PICK_MOVE_ENCODING[key].label}`,
      swatch: { kind: "text" as const, className: PICK_MOVE_ENCODING[key].className },
    })),
  ];
}
