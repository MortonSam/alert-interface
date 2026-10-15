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
