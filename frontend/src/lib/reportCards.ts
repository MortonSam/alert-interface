// The Evidence section's report cards: one per stored earnings reaction, newest first. Each card states the report date and
// timing, one line for EPS against the estimate, and the 1-, 3- and 5-day moves. Tapping a card opens a line built only from
// the same row's stored facts and the stock's typical earnings move from the reaction summary; a missing fact leaves its part out.
import type { HistoricalReaction, ReactionSummary } from "@/lib/api";
import { EPS_SURPRISE_PCT_CAP } from "@/lib/thresholds";
import { compareMoves, MOVE_MIN_REPORTS, type MoveComparison } from "@/lib/optionsVerdict";
import { fmtDay } from "@/lib/tickerDates";

export const TIMING_WORDS: Record<string, string> = { bmo: "Before the open", amc: "After the close" };

export interface CardMove { key: "1d" | "3d" | "5d"; label: string; value: number | null }

export interface ReportCard {
  id: string;
  eventDate: string;            // the stored date, "2026-07-22"
  date: string;                 // "Jul 22, 2026"
  timing: string | null;        // "After the close", null when the timing is unknown
  eps: string | null;           // the EPS line, null when no judged figure is stored
  epsAbsent: string | null;     // why there is no EPS line
  moves: CardMove[];
}

const num = (v: string | number | null | undefined): number | null => {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

/** The outcome the row's stored figures support, or null: a beat, miss or meet needs a stored actual and estimate and no basis reason. */
export function judgedOutcome(r: HistoricalReaction): "beat" | "miss" | "meet" | null {
  if (r.outcome_reason || r.basis_mismatch) return null;
  if (num(r.eps_actual) == null || num(r.eps_estimate) == null) return null;
  return r.outcome === "beat" || r.outcome === "miss" || r.outcome === "meet" ? r.outcome : null;
}

/** The surprise size in words: "17.1%", "$0.06" when the estimate is near zero, "more than 999%" past the cap. Null when none. */
export function surpriseSize(r: HistoricalReaction): string | null {
  if (r.eps_surprise_pct == null) {
    const d = r.eps_surprise_dollars;
    return d == null ? null : `$${Math.abs(d).toFixed(2)}`;
  }
  const capped = r.eps_surprise_capped ?? Math.abs(r.eps_surprise_pct) > EPS_SURPRISE_PCT_CAP;
  if (capped) return `more than ${EPS_SURPRISE_PCT_CAP}%`;
  const shown = r.eps_surprise_display_pct ?? r.eps_surprise_pct;
  return `${Math.abs(shown).toFixed(1)}%`;
}

const NO_EPS = "No EPS figure is stored for this report.";

/** "EPS $0.41 against a $0.35 estimate, a 17.1% beat" */
export function epsLine(r: HistoricalReaction): { eps: string | null; epsAbsent: string | null } {
  const outcome = judgedOutcome(r);
  if (!outcome) return { eps: null, epsAbsent: r.outcome_reason ?? NO_EPS };
  const a = num(r.eps_actual)!, e = num(r.eps_estimate)!;
  const base = `EPS $${a.toFixed(2)} against a $${e.toFixed(2)} estimate`;
  if (outcome === "meet") return { eps: `${base}, in line`, epsAbsent: null };
  const size = surpriseSize(r);
  return { eps: size ? `${base}, a ${size} ${outcome}` : `${base}, a ${outcome}`, epsAbsent: null };
}

export function reportCard(r: HistoricalReaction): ReportCard {
  return {
    id: r.id,
    eventDate: r.event_date,
    date: fmtDay(r.event_date) ?? r.event_date,
    timing: r.report_timing ? TIMING_WORDS[r.report_timing] ?? null : null,
    ...epsLine(r),
    moves: [
      { key: "1d", label: "1 day", value: num(r.pct_change_1d) },
      { key: "3d", label: "3 days", value: num(r.pct_change_3d) },
      { key: "5d", label: "5 days", value: num(r.pct_change_5d) },
    ],
  };
}

/** Earnings rows newest first, as cards. */
export function reportCards(rows: HistoricalReaction[]): ReportCard[] {
  return [...rows].sort((a, b) => b.event_date.localeCompare(a.event_date)).map(reportCard);
}

/** "+8.7%" with the sign the value has at one decimal. */
export function fmtMove(v: number): string {
  const r = Number(v.toFixed(1));
  return `${r > 0 ? "+" : ""}${r.toFixed(1)}%`;
}

/** The typical earnings move a card compares with: the summary's mean absolute 1-day move, only over at least MOVE_MIN_REPORTS
 * stored reports (the rule Discover's comparison uses). */
export interface TypicalMove { pct: number; reports: number; through: string | null }

type SummaryLike = Pick<ReactionSummary, "avg_abs_1d" | "total_quarters" | "last_event_date"> & { exclusion_reason?: string | null; deal_note?: string | null; held?: boolean };

/** The summary's typical move as stored, whatever its sample size; null when none is stored, the ticker's figures are withheld,
 * or the typical move is held (backend services/fact_holds), so neither the cards nor the verdict compare with it. */
export function storedTypical(s: SummaryLike | null | undefined): TypicalMove | null {
  if (!s || s.exclusion_reason || s.deal_note || s.held || s.avg_abs_1d == null || s.avg_abs_1d <= 0) return null;
  return { pct: s.avg_abs_1d, reports: s.total_quarters, through: s.last_event_date };
}

/** The typical move a comparison may use: at least MOVE_MIN_REPORTS stored reports behind it. */
export function typicalMove(s: SummaryLike | null | undefined): TypicalMove | null {
  const t = storedTypical(s);
  return t && t.reports >= MOVE_MIN_REPORTS ? t : null;
}

const COMPARE_WORDS: Record<MoveComparison, string> = {
  "more than usual": "more than its typical",
  "less than usual": "less than its typical",
  "about its usual": "about its typical",
};

export interface WhyLine { text: string; comparison: MoveComparison | null; receipt: string | null }

/** The tapped card's line, from stored facts only:
 *  "EPS beat the estimate by 17.1%. The stock fell 3.6% over the first trading day after the report, less than its typical 8.7% move."
 * Each sentence appears only when its facts are stored. Null when nothing is. */
export function whyItMoved(r: HistoricalReaction, typical: TypicalMove | null): WhyLine | null {
  const parts: string[] = [];
  const outcome = judgedOutcome(r);
  if (outcome) {
    const size = surpriseSize(r);
    if (outcome === "meet") parts.push("EPS matched the estimate.");
    else parts.push(size ? `EPS ${outcome === "beat" ? "beat" : "missed"} the estimate by ${size}.` : `EPS ${outcome === "beat" ? "beat" : "missed"} the estimate.`);
  }
  const move = num(r.pct_change_1d);
  let comparison: MoveComparison | null = null;
  let receipt: string | null = null;
  if (move != null) {
    const size = Math.abs(Number(move.toFixed(1)));
    const verb = size === 0 ? "was unchanged" : `${move > 0 ? "rose" : "fell"} ${size.toFixed(1)}%`;
    let sentence = `The stock ${verb} over the first trading day after the report`;
    if (typical) {
      const typ = Number(typical.pct.toFixed(1));
      comparison = compareMoves(size, typ);
      sentence += `, ${COMPARE_WORDS[comparison]} ${typ.toFixed(1)}% move`;
      const through = fmtDay(typical.through);
      receipt = `Typical move is the average size of the first-day move across ${typical.reports} reports${through ? ` through ${through}` : ""}.`;
    }
    parts.push(`${sentence}.`);
  }
  return parts.length ? { text: parts.join(" "), comparison, receipt } : null;
}
