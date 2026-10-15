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

/**
 * Street Pulse's line (2026-10-15). A median move on analyst actions is called a reaction only when it is larger than the stock's
 * own median absolute daily move over the same years (the API's median_abs_daily_move_pct); at or inside it the line says there
 * was no clear reaction, and without that figure there is no line. The side with more sessions speaks (downgrades on a tie).
 */
export function streetPulseLine(
  stats: {
    median_1d_upgrade: number | null; median_1d_downgrade: number | null; upgrade_sessions: number; downgrade_sessions: number;
    upgrade_5d_continuation_pct: number | null; downgrade_5d_continuation_pct: number | null; median_abs_daily_move_pct?: number | null;
  },
  fmtPct: (n: number) => string,
  later: string,
): string | null {
  const up = hasAnalystSignal(stats.median_1d_upgrade, stats.upgrade_sessions);
  const dn = hasAnalystSignal(stats.median_1d_downgrade, stats.downgrade_sessions);
  if (!up && !dn) return null;
  const usual = stats.median_abs_daily_move_pct ?? null;
  if (usual == null) return null;
  const down = dn && (!up || stats.downgrade_sessions >= stats.upgrade_sessions);
  const med = (down ? stats.median_1d_downgrade : stats.median_1d_upgrade) as number;
  const kind = down ? "Downgrades" : "Upgrades";
  if (Math.abs(med) <= usual) return `${kind} have brought no clear reaction, a median ${fmtPct(med)} on the day against a usual daily move of ±${usual.toFixed(1)}%.`;
  let line = `${kind} tend to ${med < 0 ? "hit" : "lift"}, median ${fmtPct(med)} on the day`;
  const cont = down ? stats.downgrade_5d_continuation_pct : stats.upgrade_5d_continuation_pct;
  if (cont != null) line += `, still ${down ? "lower" : "higher"} ${later} ${cont.toFixed(0)}% of the time`;
  return line + ".";
}
