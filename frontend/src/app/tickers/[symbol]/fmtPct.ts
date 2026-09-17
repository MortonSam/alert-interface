/** Format percentage, collapsing -0.0 to 0.0, with sign prefix. */
export function fmtPct(v: number, digits = 1): string {
  const rounded = Number(v.toFixed(digits));
  // Object.is catches -0
  const display = Object.is(rounded, -0) ? 0 : rounded;
  const sign = display > 0 ? "+" : "";
  return `${sign}${display.toFixed(digits)}%`;
}
