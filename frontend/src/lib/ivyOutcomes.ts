// Labels for every outcome the nightly evaluation can record, and the sentence
// that summarises a night. Mirrors backend/app/services/ivy_outcomes.py; a
// vitest reads that file and fails if an outcome has no label here.

export const IVY_OUTCOME_LABELS: Record<string, string> = {
  picked: "Picked",
  vol_gate: "Refused: options too expensive for the edge",
  no_fresh_chain: "Refused: no current options data",
  structure_failed: "Refused: could not build the spread from the available strikes",
  momentum_gate: "Passed: no momentum setup",
  insufficient_history: "Passed: not enough earnings history",
  no_features: "Passed: no data for this name",
  open_pick_exists: "Holding: already has an open pick in this name",
  cap_reached: "Passed: pick limit reached",
  mixed_evidence: "Passed: signals disagreed (earlier engine)",
  error: "Error during evaluation",
};

export function ivyOutcomeLabel(outcome: string): string {
  return IVY_OUTCOME_LABELS[outcome] ?? "Outcome not recognised";
}

interface NightCounts { evaluated: number; picked: number; refused: number; passed: number; holding?: number; errors: number }

/** "evaluated 41 names: picked 1, refused 6, passed 33, holding 1, 1 error" : five kinds, never lumped. */
export function nightSummary(c: NightCounts): string {
  const names = `${c.evaluated} ${c.evaluated === 1 ? "name" : "names"}`;
  const parts = [`picked ${c.picked}`, `refused ${c.refused}`, `passed ${c.passed}`, `holding ${c.holding ?? 0}`];
  if (c.errors > 0) parts.push(`${c.errors} ${c.errors === 1 ? "error" : "errors"}`);
  return `evaluated ${names}: ${parts.join(", ")}`;
}

export const NIGHT_SUMMARY_KEY =
  "Refused means the setup was there and she declined it. Passed means the setup was not there. " +
  "Holding means she already has an open pick on the name and does not double up.";

/**
 * Why the implied-move cell is empty. The stored implied_reason is the fact; without one
 * (rows written before it existed) the cell says the pricing was not recorded, never a
 * failure the evaluation did not have.
 */
export function impliedMoveAbsentLabel(outcome: string, impliedReason?: string | null): string {
  if (impliedReason) return impliedReason;
  return outcome === "no_fresh_chain" ? "not priced: no current options data" : "not priced: reason not recorded";
}

/** What an anonymous visitor sees while the ledger is private: the same wording on the desk and the trades page. */
export const PRIVATE_LEDGER_TITLE = "Recording nightly";
export const PRIVATE_LEDGER_BODY =
  "Ivy's worksheet and ledger are recorded every night and go public at launch. Every pick is timestamped before the outcome is known.";

/** "06:16Z" from an ISO UTC timestamp; the nightly is a UTC event. */
function fmtUtcClock(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}Z`;
}

export interface RunStatusFields {
  last_run_at?: string | null;
  last_run_exit?: number | null;
  last_run_error?: string | null;
  last_run_stale?: boolean;
  last_run_failed?: boolean;
}

/**
 * The sentence the desk shows when the latest Auto-pick run did not complete.
 * Null when the latest run is clean and current. `worksheetDate` is the
 * worksheet being shown instead (already formatted), or null when there is none.
 */
export function runFailureLine(run: RunStatusFields, worksheetDate: string | null): string | null {
  if (!run.last_run_failed) return null;
  const when = run.last_run_at ? ` at ${fmtUtcClock(run.last_run_at)}` : "";
  let head: string;
  if (run.last_run_at == null) {
    head = "Ivy's nightly evaluation has not run yet";
  } else if (run.last_run_stale && (run.last_run_exit ?? 0) === 0) {
    head = `Ivy's nightly evaluation did not run last night (last completed${when} on ${run.last_run_at.slice(0, 10)})`;
  } else {
    head = `Last night's evaluation did not complete (exit ${run.last_run_exit ?? "unknown"}${when})`;
  }
  const error = run.last_run_error ? `: ${run.last_run_error}` : "";
  const tail = worksheetDate ? ` Showing the ${worksheetDate} worksheet.` : " No worksheet to show yet.";
  return `${head}${error}.${tail}`;
}
