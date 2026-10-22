// What opens the Options section's Details (Sam, 2026-10-22, verbatim wording): two paired figures, the total move the options
// price by the expiration and how much of it comes from the report, then one small line with the range, the straddle and the
// options data's date. They replaced Sam's 2026-10-20 sentence ("Options price a move of about 9.2% by ...") and the
// "$19.65 implied move" line. Every figure comes from the same API facts the verdict reads (expected_move_pct,
// expected_move_dollars, implied_range_low/high, atm_strike, chain_date, report_move.pct).
import { fmtDate } from "@/lib/dates";
import { fmtDollars } from "@/lib/optionFactFormat";

const pct1 = (x: number) => (x * 100).toFixed(1);

export type OptionsFigure = { value: string; sub: string | null; label: string };
export type OptionsFigures = { total: OptionsFigure; report: OptionsFigure | null; detail: string | null };

/** The left figure ("±8.9%", "$19.65 either way", "Options price by Nov 20, 2026"), the right one only with a report move in the
 * window ("about 4.4%", "of that from the report", "The rest is ordinary day-to-day swing"), and the small line from whatever of
 * the range, straddle and data date is present. Null without a total move or its date. */
export function optionsFigures(f: {
  totalPct: number | null | undefined; totalDollars: number | null | undefined; expiration: string | null | undefined;
  reportPct: number | null | undefined; reportState: string | null | undefined;
  low: number | null | undefined; high: number | null | undefined; atmStrike: number | null | undefined; chainDate: string | null | undefined;
}): OptionsFigures | null {
  const by = fmtDate(f.expiration ? f.expiration.slice(0, 10) : null);
  if (f.totalPct == null || !by) return null;
  const total = { value: `±${pct1(f.totalPct)}%`, sub: f.totalDollars != null ? `${fmtDollars(f.totalDollars)} either way` : null, label: `Options price by ${by}` };
  const report = f.reportState === "ok" && f.reportPct != null
    ? { value: `about ${pct1(f.reportPct)}%`, sub: "of that from the report", label: "The rest is ordinary day-to-day swing" }
    : null;
  const parts: string[] = [];
  if (f.low != null && f.high != null) parts.push(`Implied range ${fmtDollars(f.low)} to ${fmtDollars(f.high)}`);
  if (f.atmStrike != null && f.totalDollars != null) parts.push(`at-the-money ${fmtDollars(f.atmStrike)} straddle at ${fmtDollars(f.totalDollars)}`);
  const asOf = fmtDate(f.chainDate ? f.chainDate.slice(0, 10) : null);
  if (asOf) parts.push(`from the ${asOf} options data`);
  return { total, report, detail: parts.length ? parts.join(" · ") : null };
}
