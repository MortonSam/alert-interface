// The Evidence section's two-way switch at the top: Chart (the reaction chart, distribution, peers and the table) and Reports (the
// tap-a-report cards). The first entry is the view the section opens on (Chart, Sam's live review 2026-10-20). Picking a report on
// the chart opens Reports at that report's card, and Reports then offers BACK_TO_CHART.
export type EvidenceView = "reports" | "chart";

export const EVIDENCE_VIEWS: { key: EvidenceView; label: string }[] = [
  { key: "chart", label: "Chart" },
  { key: "reports", label: "Reports" },
];

export const BACK_TO_CHART = "Back to the chart";

/** A report picked on the chart: its date, and a count so picking the same report again scrolls to it again. */
export interface PickedReport { date: string; n: number }

/** How long a picked card stays highlighted, in milliseconds. */
export const PICK_HIGHLIGHT_MS = 1600;

/** "smooth" unless the visitor asked for reduced motion. */
export function smoothScroll(): ScrollBehavior {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}
