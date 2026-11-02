// The walkthrough charts' time axis (Sam, 2026-10-19): points sit at their dates, not at their count, so a year takes a year's width
// however many points it has, and a stretch with no points shows as a gap in the line, never a line drawn across it.

const DAY_MS = 86_400_000;
/** The backend sends every fifth session (walkthrough.CHART_EVERY), about a week apart; a longer run without a point is a gap. */
export const GAP_DAYS = 21;

/** A calendar day ("2026-10-16") as milliseconds at noon UTC, so no zone moves it. */
export const dayMs = (iso: string): number => Date.parse(iso.slice(0, 10) + "T12:00:00Z");     // an axis position, never shown

/** Rows on a time axis: each row's t is its day in milliseconds; where two rows sit more than GAP_DAYS apart, a row with every
 *  series null goes between them, so the line breaks there (connectNulls off). */
export function timeRows<R extends Record<string, unknown>>(rows: (R & { d: string })[], keys: string[], gapDays = GAP_DAYS): (R & { t: number })[] {
  const out: (R & { t: number })[] = [];
  const sorted = [...rows].sort((a, b) => a.d.localeCompare(b.d));
  for (const r of sorted) {
    const t = dayMs(r.d);
    const prev = out[out.length - 1];
    if (prev && t - prev.t > gapDays * DAY_MS) {
      out.push({ ...(Object.fromEntries(keys.map((k) => [k, null])) as unknown as R), d: "", t: prev.t + DAY_MS });
    }
    out.push({ ...r, t });
  }
  return out;
}

/** Jan 1 of each year inside [t0, t1], as ticks on the time axis. */
export function yearTicks(t0: number, t1: number): number[] {
  const out: number[] = [];
  for (let y = new Date(t0).getUTCFullYear() + 1; y <= new Date(t1).getUTCFullYear(); y++) out.push(Date.UTC(y, 0, 1, 12));
  return out;
}

/** The 1st of every `step`-th month inside [t0, t1] (counted from January), as ticks on the time axis. */
export function monthTicks(t0: number, t1: number, step = 2): number[] {
  const out: number[] = [];
  const s = new Date(t0);
  for (let y = s.getUTCFullYear(), m = s.getUTCMonth() + 1; ; m++) {
    if (m > 11) { m = 0; y++; }
    const t = Date.UTC(y, m, 1, 12);
    if (t > t1) break;
    if (m % step === 0) out.push(t);
  }
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthLabel = (t: number) => { const d = new Date(t); return `${MONTHS[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`; };
export const yearLabel = (t: number) => String(new Date(t).getUTCFullYear());
