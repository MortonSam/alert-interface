import type { LegendItem } from "./encodings/types";
// How an option mark describes itself. One label per backend mark_basis
// (backend/app/schemas/thesis.py MARK_BASES); a vitest fails if one is missing.
// Dates come from their own fields and are never parsed out of a sentence.

export const MARK_BASIS_LABELS = {
  ingested_chain: "marked from stored options data",
  settled: "settled at the expiration-day close",
  intrinsic: "intrinsic value, expiration close unavailable",
  not_found: "mark unavailable",
  no_option_leg: "no option leg",
} as const;

export type MarkBasis = keyof typeof MARK_BASIS_LABELS;

/** Legend rows for the ways an option mark can be derived (no_option_leg is not a mark). */
export function markBasisLegend(): LegendItem[] {
  return (Object.keys(MARK_BASIS_LABELS) as MarkBasis[])
    .filter((k) => k !== "no_option_leg")
    .map((key) => ({ key, label: MARK_BASIS_LABELS[key], swatch: { kind: "text", className: "text-muted-foreground" } }));
}

export function markBasisLabel(basis: string): string {
  return MARK_BASIS_LABELS[basis as MarkBasis] ?? "mark basis unknown";
}

/** "HH:MM:SS" today, "EEE HH:MM" otherwise, or null when the input is not a real timestamp. */
export function fmtTimestamp(iso: string | null | undefined, now: Date = new Date()): string | null {
  // Strict ISO-8601 only: V8 will happily "parse" a sentence that contains a date.
  if (!iso || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(iso)) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  return sameDay
    ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : d.toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

interface MarkDates {
  mark_basis: string;
  chain_date?: string | null;
  options_as_of?: string | null;
}

/** What the option values are as of, from the mark's own fields. Empty when unknown. */
export function optionsAsOfLabel(mark: MarkDates): string {
  if (mark.mark_basis === "settled" && mark.options_as_of) return `settled ${mark.options_as_of}`;
  if (mark.chain_date) return `options data as of ${mark.chain_date}`;
  return "";
}
