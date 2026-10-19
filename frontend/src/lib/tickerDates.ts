// The one date and time format the ticker page's header, Evidence and Options sections use: "Oct 12, 2026" and
// "4:00 PM ET", always on the New York clock. Every date passed in comes from the data (a bar, a quote, a chain, a report).

import { fmtDate, fmtTime } from "@/lib/dates";

const NY = "America/New_York";

/** "Oct 12, 2026" from "2026-10-12" or a full ISO timestamp (the New York date of the instant), through lib/dates. Null when unparseable. */
export function fmtDay(iso: string | null | undefined): string | null {
  return iso ? fmtDate(iso) : null;
}

/** "Oct 12, 2026" from a Unix time in seconds, on the New York clock. */
export function fmtDayUnix(unix: number | null | undefined): string | null {
  return unix == null ? null : fmtDay(new Date(unix * 1000).toISOString());
}

/** "4:00 PM ET" from a Unix time in seconds. */
export function fmtTimeUnix(unix: number | null | undefined): string | null {
  return unix == null ? null : fmtTime(unix);
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
  const day = (iso: string) => Date.parse(iso.slice(0, 10) + "T00:00:00Z");
  return Math.round((day(toIso) - day(fromIso)) / 86_400_000);
}
