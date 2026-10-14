// The one date and time format the ticker page's header, Evidence and Options sections use: "Oct 12, 2026" and
// "4:00 PM ET", always on the New York clock. Every date passed in comes from the data (a bar, a quote, a chain, a report).

const NY = "America/New_York";

/** "Oct 12, 2026" from "2026-10-12" or a full ISO timestamp (the New York date of the instant). Null when unparseable. */
export function fmtDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const d = new Date(`${iso}T12:00:00Z`);
    return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  }
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: NY });
}

/** "Oct 12, 2026" from a Unix time in seconds, on the New York clock. */
export function fmtDayUnix(unix: number | null | undefined): string | null {
  return unix == null ? null : fmtDay(new Date(unix * 1000).toISOString());
}

/** "4:00 PM ET" from a Unix time in seconds. */
export function fmtTimeUnix(unix: number | null | undefined): string | null {
  if (unix == null) return null;
  const d = new Date(unix * 1000);
  return Number.isNaN(d.getTime()) ? null : `${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: NY })} ET`;
}

/** The New York calendar date ("2026-10-12") and minutes after midnight of an instant in milliseconds, with its weekday (0 Sunday). */
export function nyClock(ms: number): { date: string; minutes: number; weekday: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: NY, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short",
  }).formatToParts(new Date(ms));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { date: `${get("year")}-${get("month")}-${get("day")}`, minutes: Number(get("hour")) * 60 + Number(get("minute")), weekday };
}

/** Whole days from one "YYYY-MM-DD" date to another. */
export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`) - Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`)) / 86_400_000);
}
