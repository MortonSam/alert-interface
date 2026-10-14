// The Options section's opening: one verdict sentence and a range band, from stored values only. The implied move is the one
// the section already shows (displayedOptionFacts: Ivy's Read fact block while a read is shown, else the expected-move
// endpoint), to the first expiration that captures the next report. The typical move is the reaction summary's mean absolute
// 1-day move. The comparison words follow backend services/move_comparison (MORE_RATIO, LESS_RATIO, MIN_REPORTS, mirrored by
// test) and are said only when the stored numbers support them; otherwise the sentence states the implied move alone and says why.
import { EXPIRY_CAVEAT_DAYS } from "@/lib/thresholds";
import { daysBetween, fmtDay } from "@/lib/tickerDates";

// Mirror of backend/app/services/move_comparison.py (lib/__tests__/optionsVerdict.test.ts reads the backend file).
export const MOVE_MORE_RATIO = 1.2;
export const MOVE_LESS_RATIO = 0.8;
export const MOVE_MIN_REPORTS = 8;

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

export interface VerdictInput {
  symbol: string;
  facts: VerdictFacts;
  nextReport: string | null;                     // the ticker's next report date
  confirmation: string | null | undefined;       // its confirmation level; only "confirmed" is priced (services/implied_move.implied_move_allowed)
  typical: { pct: number; reports: number; through: string | null } | null;
  quote: { price: number | null; asOf: string | null } | null;   // the latest stored quote, with its date words
}

export interface RangeBand {
  low: number; high: number;
  marker: number; markerLabel: string;   // the price shown inside the band and what it is
  by: string;                            // "Nov 20, 2026"
  lowPos: number; highPos: number; markerPos: number;   // 0-100 along the bar
}

export type Verdict =
  | { kind: "verdict"; sentence: string; comparison: MoveComparison | null; impliedPct: number; typicalPct: number | null; why: string | null; receipt: string; band: RangeBand | null }
  | { kind: "absent"; line: string };

/** The band's geometry: low and high with a margin, the marker clamped inside the bar. */
export function rangeBand(low: number, high: number, marker: number, markerLabel: string, by: string): RangeBand {
  const lo = Math.min(low, marker), hi = Math.max(high, marker);
  const pad = (hi - lo) * 0.12 || hi * 0.01 || 1;
  const min = lo - pad, max = hi + pad;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
  return { low, high, marker, markerLabel, by, lowPos: pos(low), highPos: pos(high), markerPos: pos(marker) };
}

export function optionsVerdict(v: VerdictInput): Verdict {
  const f = v.facts;
  if (!v.nextReport) return { kind: "absent", line: `No upcoming report date is stored for ${v.symbol}, so there is no options verdict.` };
  if (v.confirmation !== "confirmed") {
    return { kind: "absent", line: `${v.symbol} has not confirmed its next report date, so options are not read against it yet.` };
  }
  if (f.expected_move_pct == null || !f.expiration_used || !f.chain_date) {
    return { kind: "absent", line: `No usable options prices are stored for ${v.symbol}, so there is no options verdict.` };
  }
  if (f.next_earnings_date && f.next_earnings_date.slice(0, 10) !== v.nextReport.slice(0, 10)) {
    return { kind: "absent", line: `The stored options data was priced for a different report date, so there is no options verdict.` };
  }
  const imp = Number((f.expected_move_pct * 100).toFixed(1));
  const by = fmtDay(f.expiration_used)!;
  const report = fmtDay(v.nextReport)!;
  const daysPast = daysBetween(v.nextReport, f.expiration_used);
  let comparison: MoveComparison | null = null;
  let typ: number | null = null;
  let why: string | null = null;
  if (daysPast > EXPIRY_CAVEAT_DAYS) {
    why = `That expiration is ${daysPast} days after the ${report} report, so the move covers more than the report and is not compared with its typical move.`;
  } else if (!v.typical || v.typical.pct <= 0) {
    why = "No typical earnings move is on file for this stock, so the move is not compared with one.";
  } else if (v.typical.reports < MOVE_MIN_REPORTS) {
    why = `Only ${v.typical.reports} past reports are stored, fewer than the ${MOVE_MIN_REPORTS} a typical move needs, so the move is not compared with one.`;
  } else {
    typ = Number(v.typical.pct.toFixed(1));
    comparison = compareMoves(imp, typ);
  }
  const words: Record<MoveComparison, string> = {
    "more than usual": "more than its typical",
    "less than usual": "less than its typical",
    "about its usual": "about the same as its typical",
  };
  const sentence = comparison && typ != null
    ? `Options are pricing a move of about ${imp.toFixed(1)}% by ${by}, ${words[comparison]} ${typ.toFixed(1)}% move after a report.`
    : `Options are pricing a move of about ${imp.toFixed(1)}% by ${by}.`;
  const through = fmtDay(v.typical?.through ?? null);
  const receipt = `From the ${fmtDay(f.chain_date)} options data, for the report on ${report}.`
    + (comparison && v.typical ? ` Typical move is the average size of the first-day move across ${v.typical.reports} reports${through ? ` through ${through}` : ""}.` : "");

  let band: RangeBand | null = null;
  if (f.implied_range_low != null && f.implied_range_high != null) {
    const useQuote = v.quote?.price != null && v.quote.asOf;
    const marker = useQuote ? v.quote!.price! : f.current_price;
    const label = useQuote ? v.quote!.asOf! : (fmtDay(f.price_as_of) ? `price on ${fmtDay(f.price_as_of)}` : null);
    if (marker != null && label) band = rangeBand(f.implied_range_low, f.implied_range_high, marker, label, by);
  }
  return { kind: "verdict", sentence, comparison, impliedPct: imp, typicalPct: typ, why, receipt, band };
}
