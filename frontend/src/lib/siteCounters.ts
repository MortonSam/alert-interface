import type { SiteStats } from "@/lib/api";
import { insightAsOfLine } from "@/lib/insightHeadline";

export interface CounterRow {
  key: string;
  value: number;
  label: string;
  title: string | null;     // the hover: only the date the count rests on ("As of Oct 1, 2026"; the chain count adds its source)
}

/** The four homepage counters, each a live count from a stored table, dated by its own newest row. Labels as written. */
export function counterRows(stats: SiteStats | null): CounterRow[] {
  if (!stats) return [];
  const contractsAsOf = insightAsOfLine(stats.option_contracts_as_of);
  return [
    { key: "contracts", value: stats.option_contracts_captured, label: "option contracts captured nightly",
      title: contractsAsOf ? `${contractsAsOf} (${stats.option_contracts_source})` : null },
    { key: "prices", value: stats.licensed_daily_prices, label: "licensed daily prices", title: insightAsOfLine(stats.licensed_daily_prices_as_of) },
    { key: "earnings", value: stats.earnings_reports_measured, label: "earnings reactions measured", title: insightAsOfLine(stats.earnings_reports_as_of) },
    { key: "analyst", value: stats.analyst_reactions_measured, label: "analyst actions measured", title: insightAsOfLine(stats.analyst_reactions_as_of) },
  ];
}
