/**
 * Sample wording for analyst reaction stats.
 *
 * The backend stores `*_count` (actions) and `*_sessions` (distinct event
 * dates). Every statistic is taken over sessions: several actions on one day
 * share one price move, so they are one observation. When the two differ the
 * label says so, otherwise the plain count reads the same either way.
 */
export function analystSampleLabel(actions: number, sessions: number, suffix = ""): string {
  const tail = suffix ? ` ${suffix}` : "";
  if (actions === sessions) return `${actions}${tail}`;
  return `n = ${actions} actions across ${sessions} sessions${tail}`;
}

/** "Based on …" footer: totals across both directions. */
export function analystSampleFooter(actions: number, sessions: number): string {
  if (actions === sessions) return `Based on ${actions} actions`;
  return `Based on n = ${actions} actions across ${sessions} sessions`;
}
