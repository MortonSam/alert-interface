import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Qualitative tag + color for an RV rank value (0–100). */
export function rvRankShort(rank: number): { tag: string; colorClass: string } {
  if (rank < 20) return { tag: "very low", colorClass: "text-blue-500 dark:text-blue-400" };
  if (rank < 40) return { tag: "low", colorClass: "text-blue-500 dark:text-blue-400" };
  if (rank < 60) return { tag: "average", colorClass: "text-muted-foreground" };
  if (rank < 80) return { tag: "high", colorClass: "text-amber-600 dark:text-amber-400" };
  return { tag: "very high", colorClass: "text-amber-600 dark:text-amber-400" };
}
