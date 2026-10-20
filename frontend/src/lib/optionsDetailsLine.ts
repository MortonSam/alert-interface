// The line that opens the Options section's Details (Sam, 2026-10-20, verbatim): the total move the options price by the
// expiration, then how much of it comes from the report. It replaced a large "±9.2%" that read as a contradiction of the verdict's
// report-only move above it. Both figures come from the same API facts the verdict reads (expected_move_pct, report_move.pct).
import { fmtDate } from "@/lib/dates";

const pct1 = (x: number) => (x * 100).toFixed(1);

/** "Options price a move of about 9.2% by Nov 20, 2026 in total. About 4.3% of that comes from the report itself; the rest is the
 * stock's ordinary day-to-day swing." The second sentence only with a report move ("ok"); null without a total move or its date. */
export function optionsDetailsLine(totalPct: number | null | undefined, expiration: string | null | undefined,
                                   reportPct: number | null | undefined, reportState: string | null | undefined): string | null {
  const by = fmtDate(expiration ? expiration.slice(0, 10) : null);
  if (totalPct == null || !by) return null;
  const total = `Options price a move of about ${pct1(totalPct)}% by ${by} in total.`;
  if (reportState !== "ok" || reportPct == null) return total;
  return `${total} About ${pct1(reportPct)}% of that comes from the report itself; the rest is the stock's ordinary day-to-day swing.`;
}
