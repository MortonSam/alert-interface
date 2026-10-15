/**
 * The one date format (DESIGN.md). Every date a page shows is "Oct 15, 2026"; every time is "Oct 15, 2026, 4:00 PM ET", on the New
 * York clock. A chart axis alone may shorten its tick labels (axisDay "Oct 15", axisTime "4:00 PM", axisYear "2026"), because a tick
 * sits on a labelled axis whose span the chart states. No page calls toLocaleDateString or toLocaleString for a date: the test
 * lib/__tests__/designRules.test.ts fails on any call outside this file.
 */
export const MARKET_TZ = "America/New_York";

/** A calendar date ("2026-10-15") is a day, not an instant: it is read at noon UTC and formatted in UTC, so no zone moves it. */
function parse(x: string | number | Date | null | undefined): { d: Date; dayOnly: boolean } | null {
  if (x == null || x === "") return null;
  if (x instanceof Date) return isNaN(x.getTime()) ? null : { d: x, dayOnly: false };
  if (typeof x === "number") return { d: new Date(x < 1e12 ? x * 1000 : x), dayOnly: false };     // unix seconds or milliseconds
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(x);
  if (m) return { d: new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 12)), dayOnly: true };
  const d = new Date(x);
  return isNaN(d.getTime()) ? null : { d, dayOnly: false };
}

/** "Oct 15, 2026" */
export function fmtDate(x: string | number | Date | null | undefined): string | null {
  const p = parse(x);
  if (!p) return null;
  return p.d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: p.dayOnly ? "UTC" : MARKET_TZ });
}

/** "Oct 15, 2026, 4:00 PM ET" */
export function fmtDateTime(x: string | number | Date | null | undefined): string | null {
  const p = parse(x);
  if (!p || p.dayOnly) return p ? fmtDate(x) : null;
  return p.d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: MARKET_TZ }) + " ET";
}

/** "4:00 PM ET": only beside a date already shown (the same day's time). */
export function fmtTime(x: string | number | Date | null | undefined): string | null {
  const p = parse(x);
  if (!p) return null;
  return p.d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: MARKET_TZ }) + " ET";
}

// ── chart axes only ──────────────────────────────────────────────────────────
export function axisDay(x: string | number | Date): string {
  const p = parse(x);
  return p ? p.d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: p.dayOnly ? "UTC" : MARKET_TZ }) : "";
}
export function axisTime(x: string | number | Date): string {
  const p = parse(x);
  return p ? p.d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: MARKET_TZ }) : "";
}
export function axisMonthYear(x: string | number | Date): string {
  const p = parse(x);
  return p ? p.d.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: p.dayOnly ? "UTC" : MARKET_TZ }) : "";
}
