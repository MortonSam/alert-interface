/** The 5Y price chart's axis: one tick on January 1 of each year inside the data, labelled with the year (2026-10-15). */
export function yearTicks(firstMs: number, lastMs: number): number[] {
  const out: number[] = [];
  for (let y = new Date(firstMs).getUTCFullYear() + 1; y <= new Date(lastMs).getUTCFullYear(); y++) {
    const t = Date.UTC(y, 0, 1);
    if (t > firstMs && t <= lastMs) out.push(t);
  }
  return out;
}

export function yearLabel(ms: number): string {
  return String(new Date(ms).getUTCFullYear());
}

/** The implied-move band on the price chart (Sam's live review, 2026-10-20): it covers only the time it describes, from the last bar
 * to the expiration the range is for, never the whole period shown. Null on the intraday periods (their axis is bars, not days),
 * without a range or an expiration, or when the expiration is not after the last bar. */
export interface ImpliedBand { x1: number; x2: number; y1: number; y2: number }

export function impliedBand(lastBarMs: number | null, expiration: string | null | undefined, low: number | null | undefined,
                            high: number | null | undefined, intraday: boolean): ImpliedBand | null {
  if (intraday || lastBarMs == null || !expiration || low == null || high == null) return null;
  const x2 = Date.parse(`${expiration}T00:00:00Z`);          // a date ("2026-11-20"), UTC midnight like the daily bars
  if (!Number.isFinite(x2) || x2 <= lastBarMs) return null;
  return { x1: lastBarMs, x2, y1: Math.min(low, high), y2: Math.max(low, high) };
}
