import type { SiteStats } from "@/lib/api";
import { insightAsOfLine } from "@/lib/insightHeadline";

export interface CounterRow {
  key: string;
  value: number;
  label: string;
  asOf: string | null;     // "As of Oct 5, 2026" for a snapshot count, "Through Sep 11, 2026" for a count whose newest row is a report; null without a date
}

/** "Through Sep 11, 2026": the newest report a reaction count has measured, in the same date format as the as-of line. */
export function throughLine(iso: string | null): string | null {
  const line = insightAsOfLine(iso);
  return line ? line.replace(/^As of /, "Through ") : null;
}

/** The four homepage counters, each from a stored count and dated by its own newest row. The stocks-covered count is a
 * snapshot ("As of"); the three reaction counts run through their newest measured report ("Through"). Nothing typed. */
export function counterRows(stats: SiteStats | null): CounterRow[] {
  if (!stats) return [];
  return [
    { key: "stocks", value: stats.active_stocks_covered, label: "Active S&P 500 stocks covered", asOf: insightAsOfLine(stats.active_stocks_as_of) },
    { key: "earnings", value: stats.earnings_reports_measured, label: "Earnings reactions measured", asOf: throughLine(stats.earnings_reports_as_of) },
    { key: "fomc", value: stats.fomc_reactions_measured, label: "Fed-day reactions measured", asOf: throughLine(stats.fomc_reactions_as_of) },
    { key: "analyst", value: stats.analyst_reactions_measured, label: "Analyst actions measured", asOf: throughLine(stats.analyst_reactions_as_of) },
  ];
}
