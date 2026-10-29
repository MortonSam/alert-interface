// The Evidence section's report cards: one per stored earnings reaction, newest first. Each card states the report date and
// timing, one line for EPS against the same quarter a year earlier, and the 1-, 3- and 5-day moves. Tapping a card opens a line built only from
// the same row's stored facts and the stock's typical earnings move from the reaction summary; a missing fact leaves its part out.
import type { HistoricalReaction, ReactionSummary } from "@/lib/api";
import { compareMoves, MOVE_MIN_REPORTS, type MoveComparison } from "@/lib/optionsVerdict";
import { fmtDay } from "@/lib/tickerDates";

export const TIMING_WORDS: Record<string, string> = { bmo: "Before the open", amc: "After the close" };

export interface CardMove { key: "1d" | "3d" | "5d"; label: string; value: number | null; pending?: boolean }

/** A longer window whose sessions have not closed yet (the first-day move is stored the night after the report, the 3- and
 * 5-day moves as each closes): shown in words, never as a zero or as missing data. */
export const MOVE_NOT_YET = "Not yet available";
export const MOVE_NOT_ON_FILE = "Not on file";

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

const NO_EPS = "No EPS figure from SEC filings for this report.";

/** The card's EPS line: the reported figure against the same quarter a year earlier (the API's eps_line, "EPS $2.22, up 111.4% from
 * $1.05 a year ago"). No estimate, beat, miss or surprise is shown anywhere (Block 2, 2026-10-20). */
export function epsLine(r: HistoricalReaction): { eps: string | null; epsAbsent: string | null } {
  return r.eps_line ? { eps: r.eps_line, epsAbsent: null } : { eps: null, epsAbsent: NO_EPS };
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
      { key: "3d", label: "3 days", value: num(r.pct_change_3d), pending: (r.pending_windows ?? []).includes("3d") },
      { key: "5d", label: "5 days", value: num(r.pct_change_5d), pending: (r.pending_windows ?? []).includes("5d") },
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
 *  "The stock fell 3.6% over the first trading day after the report, less than its typical 8.7% move."
 * Null when the move is not on file. */
export function whyItMoved(r: HistoricalReaction, typical: TypicalMove | null): WhyLine | null {
  const parts: string[] = [];
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

/** W7 (Block 2 wording): "After past reports, the stock moved +1.2% the next day on average." The figure is the API's avg_1d, the
 * mean of the signed next-day moves (backend routers/historical_reactions.signed_mean). Null when there is none. */
export function averageMoveLine(avg1d: number | null | undefined): string | null {
  return avg1d == null ? null : `After past reports, the stock moved ${fmtMove(avg1d)} the next day on average.`;
}
