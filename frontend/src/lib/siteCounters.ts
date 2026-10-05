import type { SiteStats } from "@/lib/api";
import { insightAsOfLine } from "@/lib/insightHeadline";

export interface CounterRow {
  key: string;
  value: number;
  label: string;
  asOf: string | null;     // "As of Sep 11, 2026", from the newest row the count rests on; null when the API gave no date
}

/** The four homepage counters, each from a stored count and dated by its own newest row. Nothing typed. */
export function counterRows(stats: SiteStats | null): CounterRow[] {
  if (!stats) return [];
  return [
    { key: "stocks", value: stats.active_stocks_covered, label: "Active S&P 500 stocks covered", asOf: insightAsOfLine(stats.active_stocks_as_of) },
    { key: "earnings", value: stats.earnings_reports_measured, label: "Earnings reactions measured", asOf: insightAsOfLine(stats.earnings_reports_as_of) },
    { key: "fomc", value: stats.fomc_reactions_measured, label: "Fed-day reactions measured", asOf: insightAsOfLine(stats.fomc_reactions_as_of) },
    { key: "analyst", value: stats.analyst_reactions_measured, label: "Analyst actions measured", asOf: insightAsOfLine(stats.analyst_reactions_as_of) },
  ];
}
