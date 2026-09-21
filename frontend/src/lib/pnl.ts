// Every *_pnl_pct value from the API is a PERCENT: -35 means a 35% loss.
// The backend computes all of them in one place (app/services/pnl_math.pnl_percent).
// Format and average them here; never multiply by 100 in a page.

export function fmtPnlPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

export function averagePnlPct(values: Array<number | null | undefined>): number | null {
  const nums = values.filter((v): v is number => v != null && Number.isFinite(v));
  return nums.length > 0 ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
}
