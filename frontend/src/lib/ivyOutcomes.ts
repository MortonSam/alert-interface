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
  open_pick_exists: "Passed: already holding a pick in this name",
  cap_reached: "Passed: pick limit reached",
  mixed_evidence: "Passed: signals disagreed (earlier engine)",
  error: "Error during evaluation",
};

export function ivyOutcomeLabel(outcome: string): string {
  return IVY_OUTCOME_LABELS[outcome] ?? "Outcome not recognised";
}

interface NightCounts { evaluated: number; picked: number; refused: number; passed: number; errors: number }

/** "evaluated 41 names, picked 1, refused 6, passed on 33, 1 error" : four kinds, never lumped as "passed on". */
export function nightSummary(c: NightCounts): string {
  const names = `${c.evaluated} ${c.evaluated === 1 ? "name" : "names"}`;
  const parts = [`picked ${c.picked}`, `refused ${c.refused}`, `passed on ${c.passed}`];
  if (c.errors > 0) parts.push(`${c.errors} ${c.errors === 1 ? "error" : "errors"}`);
  return `evaluated ${names}: ${parts.join(", ")}`;
}

export const NIGHT_SUMMARY_KEY =
  "Refused means the setup was there and she declined it. Passed means the setup was not there.";

/** Why the implied-move cell is empty. The two cases are different facts. */
export function impliedMoveAbsentLabel(outcome: string): string {
  return outcome === "no_fresh_chain" ? "no current options data" : "options could not be priced";
}

/** What an anonymous visitor sees while the ledger is private: the same wording on the desk and the trades page. */
export const PRIVATE_LEDGER_TITLE = "Recording nightly";
export const PRIVATE_LEDGER_BODY =
  "Ivy's worksheet and ledger are recorded every night and go public at launch. Every pick is timestamped before the outcome is known.";
