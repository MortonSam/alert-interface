// What each reaction window measures, per view. The chart tooltip, the table
// footnote, the column tooltips and the Fed-vs-earnings line all read from here.
// Earnings: timing-aware close-to-close (seed_historical_reactions._compute_v3).
// Fed: from the decision-day open (seed_historical_reactions._compute).

export type ReactionMode = "earnings" | "fed";

export const REACTION_WINDOW_TEXT = {
  earnings: {
    tooltip1d: "1-day move after the report",
    tooltip5d: "5-day move after the report",
    footnote:
      "Moves measured from the last close before the report. BMO: close(T-1) to close(T/T+2/T+4). AMC: close(T) to close(T+1/T+3/T+5).",
    glossaryTerm: { "1d": "1d move", "3d": "3d move", "5d": "5d move" },
    basis: "last close before the report to the next close",
  },
  fed: {
    tooltip1d: "Move from the Fed-day open to the next session's close",
    tooltip5d: "Move from the Fed-day open to the close five sessions later",
    footnote:
      "Fed-day moves are measured from the open on the decision day (T): open(T) to close(T+1/T+3/T+5). They span more than one session, so they are not directly comparable to the earnings moves.",
    glossaryTerm: { "1d": "fed 1d move", "3d": "fed 3d move", "5d": "fed 5d move" },
    basis: "decision-day open to the next session's close",
  },
} as const;

export function fedVsEarningsLine(fedAvg: number, earningsAvg: number): string {
  const t = REACTION_WINDOW_TEXT;
  return (
    `Avg ±${fedAvg.toFixed(1)}% around Fed decisions (${t.fed.basis}) vs ` +
    `±${earningsAvg.toFixed(1)}% around earnings (${t.earnings.basis}). Different windows, so treat as a rough comparison.`
  );
}

// Analyst actions: day 0 is the event day itself, and the later reading is the
// close on the first session at least 4 calendar days on. Measured over 9,738
// stored actions that is 2 sessions later 37% of the time, 3 sessions 21%,
// 4 sessions 40% (1 session 2%): never a full week.
export const ANALYST_WINDOW_TEXT = {
  day0: "event-day move",
  later: "2–4 sessions later",
  laterHeader: "2–4 sess.",
} as const;
