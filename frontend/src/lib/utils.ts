import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Qualitative tag + color for an RV rank value (0–100).
 *  Labels signal "relative to its own history" — not absolute volatility. */
export function rvRankShort(rank: number): { tag: string; colorClass: string } {
  if (rank < 25) return { tag: "low", colorClass: "text-muted-foreground" };
  if (rank < 70) return { tag: "normal", colorClass: "text-muted-foreground" };
  if (rank < 90) return { tag: "elevated", colorClass: "text-amber-600 dark:text-amber-400" };
  return { tag: "extreme", colorClass: "text-primary" };
}

/** Tooltip text explaining what RV rank means. */
export const RV_RANK_TIP =
  "Where this stock\u2019s current 20-day volatility sits within its OWN past year. " +
  "A high rank means it\u2019s more volatile lately than usual for this stock \u2014 " +
  "NOT that it\u2019s a volatile stock overall. A steady name can rank high if " +
  "it\u2019s currently choppier than normal.";

/** Shorter per-row version of the RV rank tooltip. */
export const RV_RANK_TIP_SHORT =
  "How volatile this stock is right now vs. its own past year. " +
  "High = choppier than usual for THIS stock, not volatile in absolute terms.";

/** Tooltip text explaining implied move. */
export const IMPLIED_MOVE_TIP =
  "The size of the move the options market is pricing in \u2014 up OR down \u2014 " +
  "by the next earnings report. It\u2019s a magnitude, not a direction or a prediction: " +
  "a bigger number means the market expects a bigger swing, either way. " +
  "Derived from the at-the-money straddle of the expiry closest to the earnings date.";
