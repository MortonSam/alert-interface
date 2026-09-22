/**
 * Sample wording for analyst reaction stats.
 *
 * The backend stores `*_count` (actions) and `*_sessions` (distinct event
 * dates). Every statistic is taken over sessions: several actions on one day
 * share one price move, so they are one observation. When the two differ the
 * label says so, otherwise the plain count reads the same either way.
 *
 * A session count of 0 next to a non-zero action count means the row has not
 * been recomputed since the sessions columns were added: the sessions are
 * unknown, not zero, so the label shows only the action count and the
 * statistics on that row are treated as no data.
 */
export function analystSampleLabel(actions: number, sessions: number, suffix = ""): string {
  const tail = suffix ? ` ${suffix}` : "";
  if (actions === sessions || sessions === 0) return `${actions}${tail}`;
  return `n = ${actions} actions across ${sessions} sessions${tail}`;
}

/** "Based on …" footer: totals across both directions. */
export function analystSampleFooter(actions: number, sessions: number): string {
  if (actions === sessions || sessions === 0) return `Based on ${actions} actions`;
  return `Based on n = ${actions} actions across ${sessions} sessions`;
}

/** A direction's median is usable only when it is stored and its session count is known. */
export function hasAnalystSignal(median: number | null | undefined, sessions: number): median is number {
  return median != null && sessions > 0;
}
