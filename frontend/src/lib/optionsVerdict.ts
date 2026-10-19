// The Options section's opening: one verdict sentence and a range band, from stored values only. The sentence is the API's own
// (backend services/report_move and services/move_comparison through the expected-move endpoint): the move the options price
// for the report alone, compared with the typical first-day move only past the move ratios. Discover's reporting-soon line states
// the same figure and sentence for the same ticker. The band is the implied range to the first expiration that captures the
// report (displayedOptionFacts). A held fact (backend services/fact_holds) drops the verdict, as Discover drops its line.
import type { ReportMove } from "@/lib/api";
import { fmtDay } from "@/lib/tickerDates";

// Mirror of backend/app/services/move_comparison.py (lib/__tests__/optionsVerdict.test.ts reads the backend file).
export const MOVE_MORE_RATIO = 1.2;
export const MOVE_LESS_RATIO = 0.8;
export const MOVE_MIN_REPORTS = 8;

// The verdict sentence is shown now that the report-only move is built; false returns the range-only opening.
export const VERDICT_SENTENCE_SHOWN = true;

export type MoveComparison = "more than usual" | "less than usual" | "about its usual";

/** services/move_comparison.compare_moves, percent units in. */
export function compareMoves(impliedPct: number, typicalPct: number): MoveComparison {
  if (typicalPct <= 0) return "about its usual";
  const ratio = Math.round((impliedPct / typicalPct) * 10_000) / 10_000;
  if (ratio > MOVE_MORE_RATIO) return "more than usual";
  if (ratio < MOVE_LESS_RATIO) return "less than usual";
  return "about its usual";
}

export interface VerdictFacts {
  expected_move_pct: number | null;      // 0-1 decimal
  implied_range_low: number | null;
  implied_range_high: number | null;
  expiration_used: string | null;
  next_earnings_date?: string | null;    // the report the expiration was chosen for
  chain_date: string | null;
  current_price: number | null;          // the price the range was computed from
  price_as_of: string | null;
}

/** The expected-move endpoint's report-move fields. Absent (state undefined) from an API that predates them. */
export interface ReportMoveFacts {
  state?: string | null;
  move?: ReportMove | null;
  comparison?: string | null;          // the API's sentence, or why there is no report move
  moveComparison?: string | null;
  typicalPct?: number | null;          // percent
  typicalN?: number | null;
  heldFacts?: string[];
}

export interface VerdictInput {
  symbol: string;
  facts: VerdictFacts;
  nextReport: string | null;                     // the ticker's next report date
  confirmation: string | null | undefined;       // its confirmation level; only "confirmed" is priced (services/implied_move.implied_move_allowed)
  report?: ReportMoveFacts | null;
  typical: { pct: number; reports: number; through: string | null } | null;   // the reaction summary's, for the receipt's date
  quote: { price: number | null; asOf: string | null } | null;   // the latest stored quote, with its date words
}

export interface RangeBand {
  low: number; high: number;
  marker: number; markerLabel: string;   // the price shown inside the band and what it is
  by: string;                            // "Nov 20, 2026"
  lowPos: number; highPos: number; markerPos: number;   // 0-100 along the bar
}

export type Verdict =
  | { kind: "verdict"; sentence: string | null; comparison: MoveComparison | null; reportPct: number | null; typicalPct: number | null; why: string | null; receipt: string | null; rangeReceipt: string; band: RangeBand | null }
  | { kind: "absent"; line: string };

/** The band's geometry: low and high with a margin, the marker clamped inside the bar. */
export function rangeBand(low: number, high: number, marker: number, markerLabel: string, by: string): RangeBand {
  const lo = Math.min(low, marker), hi = Math.max(high, marker);
  const pad = (hi - lo) * 0.12 || hi * 0.01 || 1;
  const min = lo - pad, max = hi + pad;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
  return { low, high, marker, markerLabel, by, lowPos: pos(low), highPos: pos(high), markerPos: pos(marker) };
}

const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`;

export function optionsVerdict(v: VerdictInput): Verdict {
  const f = v.facts;
  const r = v.report ?? null;
  if (!v.nextReport) return { kind: "absent", line: `No upcoming report date is on file for ${v.symbol}, so there is no options verdict.` };
  if (v.confirmation !== "confirmed") {
    return { kind: "absent", line: `${v.symbol} hasn't confirmed its next report date, so there's no options verdict yet.` };
  }
  if (r?.heldFacts?.some((x) => x === "implied_move" || x === "report_date")) {
    return { kind: "absent", line: `The options figures for ${v.symbol} are on hold while we verify them.` };
  }
  const report = fmtDay(v.nextReport)!;
  const sameReport = !f.next_earnings_date || f.next_earnings_date.slice(0, 10) === v.nextReport.slice(0, 10);
  const rangeFacts = f.expected_move_pct != null && !!f.expiration_used && !!f.chain_date && sameReport;
  let band: RangeBand | null = null;
  if (rangeFacts && f.implied_range_low != null && f.implied_range_high != null) {
    const useQuote = v.quote?.price != null && v.quote.asOf;
    const marker = useQuote ? v.quote!.price! : f.current_price;
    const label = useQuote ? v.quote!.asOf! : (fmtDay(f.price_as_of) ? `price on ${fmtDay(f.price_as_of)}` : null);
    if (marker != null && label) band = rangeBand(f.implied_range_low, f.implied_range_high, marker, label, fmtDay(f.expiration_used)!);
  }
  const rangeReceipt = `From the ${fmtDay(f.chain_date)} options data, for the report on ${report}.`;

  if (!r?.state) {            // an API without the report move: the range alone, as before it shipped
    if (!rangeFacts) {
      return { kind: "absent", line: sameReport ? `No usable options prices are on file for ${v.symbol}, so there is no options verdict.`
        : `The options data on file was priced for a different report date, so there is no options verdict.` };
    }
    return { kind: "verdict", sentence: null, comparison: null, reportPct: null, typicalPct: null, why: null, receipt: null, rangeReceipt, band };
  }

  const m = r.move;
  // the receipt names the two expirations the stated method read: around the report (pair), or the first two after it (term)
  const termLegs = m?.method === "term" || (m?.method == null && m?.before?.atm_iv == null && m?.later?.atm_iv != null);
  const [l1, l2] = termLegs ? [m?.after, m?.later] : [m?.before, m?.after];
  const legs = l1?.atm_iv != null && l2?.atm_iv != null
    ? `, the ${fmtDay(l1.expiration)} expiration at ${pct1(l1.atm_iv)} and the ${fmtDay(l2.expiration)} expiration at ${pct1(l2.atm_iv)} implied volatility`
    : "";
  const chainDay = m?.after?.chain_date ?? f.chain_date;
  const forReport = legs && termLegs ? `, the first two after the report on ${report}` : `, for the report on ${report}`;
  let receipt: string | null = chainDay ? `From the ${fmtDay(chainDay)} options data${legs}${forReport}.` : null;
  // the term method's normal volatility, raised to the 20-day realized volatility when the expirations implied less
  if (receipt && legs && termLegs && m?.base_floored && m.rv_20d != null) {
    receipt += ` The stock's usual swing is taken as its 20-day realized volatility of ${pct1(m.rv_20d)}, higher than the expirations imply.`;
  }
  const comparison = (r.moveComparison ?? null) as MoveComparison | null;
  let why: string | null = null;
  if (r.state === "ok") {
    if (comparison && v.typical) {
      const through = fmtDay(v.typical.through);
      receipt += ` Typical move is the average size of the first-day move across ${r.typicalN} reports${through ? ` through ${through}` : ""}.`;
    } else if (r.heldFacts?.includes("typical_move")) {
      why = "The typical move is on hold while we verify it, so the move is not compared with one.";
    } else if (r.typicalN != null && r.typicalN < MOVE_MIN_REPORTS) {
      why = `Only ${r.typicalN} past reports are on file, fewer than the ${MOVE_MIN_REPORTS} a typical move needs, so the move is not compared with one.`;
    } else {
      why = "No typical earnings move is on file for this stock, so the move is not compared with one.";
    }
  }
  return {
    kind: "verdict", sentence: r.comparison ?? null, comparison: r.state === "ok" ? comparison : null,
    reportPct: r.state === "ok" && m?.pct != null ? Number((m.pct * 100).toFixed(1)) : null, typicalPct: comparison ? r.typicalPct ?? null : null,
    why, receipt, rangeReceipt, band,
  };
}
