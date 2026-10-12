/**
 * The next-earnings line: the date, whether it is confirmed or estimated, and when the calendar was last asked.
 *
 * "Next earnings Oct 29, estimated (checked today)". Every part is rendered from API fields (next_earnings_date,
 * next_earnings_source, next_earnings_checked_at on a ticker; earnings_date, source, checked_at on a Discover card). A ticker
 * with no date still says when it was checked, so "none" is a finding, not a gap. No line names the calendar vendor: a visitor
 * reads "Estimated" or "Confirmed", as the Browse cards do (2026-10-12).
 */
const SOURCE_LABELS: Record<string, string> = {
  edgar: "SEC filing",
  manual: "entered by hand",
};

/** The source a visitor may be told about: a filing or a hand entry; a calendar vendor is never named. */
export function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_LABELS[source] ?? null;
}

/**
 * What kind of source confirmed a date, from the type prefix the calendar refresh writes into the note
 * (backend report_announcements / earnings_calendar). Never the headline, the filing date or a vendor that follow it.
 */
export const CONFIRMED_KIND = {
  pressRelease: "company press release",   // "confirmed: press release via <news feed> <date>: <headline>"
  secFiling: "SEC filing",                 // "confirmed: 8-K Item 7.01 filed <date>"
  calendars: "two calendars agree",        // AGREEMENT_NOTE: two calendar sources on the same day
  company: "company announcement",         // a company confirmation with no recorded evidence, or a note of no known type
} as const;

export function confirmedKind(note: string | null | undefined): string {
  const body = (note ?? "").replace(/^confirmed:\s*/i, "").trim();
  if (/^press release\b/i.test(body)) return CONFIRMED_KIND.pressRelease;
  if (/^8-K\b/i.test(body)) return CONFIRMED_KIND.secFiling;
  if (/^Finnhub and Yahoo Finance agree$/i.test(body)) return CONFIRMED_KIND.calendars;
  return CONFIRMED_KIND.company;
}

/** "checked today", "checked yesterday", "checked 3 days ago", or "not yet checked". Calendar days in the viewer's zone. */
export function checkedPhrase(checkedAt: string | null | undefined, now: Date = new Date()): string {
  if (!checkedAt) return "not yet checked";
  const t = new Date(checkedAt);
  if (isNaN(t.getTime())) return "not yet checked";
  const dayMs = 86_400_000;
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(t)) / dayMs);
  if (days <= 0) return "checked today";
  if (days === 1) return "checked yesterday";
  return `checked ${days} days ago`;
}

export function fmtEarningsDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "checked Sep 29" from an ISO timestamp, or "not yet checked". */
export function checkedOn(checkedAt: string | null | undefined): string {
  if (!checkedAt) return "not yet checked";
  const t = new Date(checkedAt);
  if (isNaN(t.getTime())) return "not yet checked";
  return `checked ${t.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}

/** The line for a ticker the calendar left without a future date: when the calendar was last asked. */
export function noDateLine(checkedAt: string | null | undefined): string {
  return checkedAt ? `No confirmed date yet (${checkedOn(checkedAt)})` : "No confirmed date yet (not yet checked)";
}

export type Confirmation = "confirmed" | "estimated" | "expected_unconfirmed";

/** The evidence phrase after "confirmed": the kind of source the API note records ("two calendars agree", "company press release"). */
function confirmedBy(note: string | null | undefined, source: string | null | undefined): string {
  return note ? confirmedKind(note) : sourceLabel(source) || CONFIRMED_KIND.company;
}

/**
 * The full line for a ticker header. The level comes from the API (next_earnings_confirmation);
 * the wording carries it, and a date that passed unconfirmed is never called past.
 */
export function nextEarningsLine(
  date: string | null | undefined,
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  confirmation: Confirmation | string | null | undefined = null,
  note: string | null | undefined = null,
  now: Date = new Date(),
): string {
  const checked = checkedPhrase(checkedAt, now);
  if (!date) return noDateLine(checkedAt);
  if (confirmation === "expected_unconfirmed") {
    return `Next earnings expected around ${fmtEarningsDate(date)}; not confirmed (${checked})`;
  }
  if (confirmation === "confirmed") {
    return `Next earnings ${fmtEarningsDate(date)}, confirmed (${confirmedBy(note, source)}; ${checked})`;
  }
  return `Next earnings ${fmtEarningsDate(date)}, estimated (${checked})`;
}

/** The badge on an event: "Confirmed", "Estimated", or "Expected, date not confirmed". Never "Past" without a report, never a vendor. */
export function eventConfirmationBadge(ev: {
  is_confirmed: boolean;
  unresolved_since?: string | null;
  source?: string | null;
}): string {
  if (ev.unresolved_since) return "Expected, date not confirmed";
  if (ev.is_confirmed) return "Confirmed";
  return "Estimated";
}

/** The whole card note: the dated line, or the no-date line, never blank. */
export function cardEarningsNote(
  date: string | null | undefined,
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  confirmation: Confirmation | string | null | undefined = null,
  note: string | null | undefined = null,
  now: Date = new Date(),
): string {
  if (!date) return noDateLine(checkedAt);
  if (confirmation === "expected_unconfirmed") return `Earnings expected around ${fmtEarningsDate(date)}; not confirmed`;
  if (confirmation === "confirmed") return `Earnings ${fmtEarningsDate(date)}, confirmed (${confirmedBy(note, source)})`;
  return `Earnings ${fmtEarningsDate(date)}, estimated \u00B7 ${earningsSourceNote(source, checkedAt, now)}`;
}

/** The short form under a Discover card: "checked today" (the calendar vendor is never named). */
export function earningsSourceNote(
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  now: Date = new Date(),
): string {
  return checkedPhrase(checkedAt, now);
}


/** The Browse the market card's earnings line: the date and whether it is confirmed or estimated, nothing else (no source, no
 *  check time, no press-release text). */
export function gridEarningsLine(date: string | null | undefined, confirmation: Confirmation | string | null | undefined): string {
  if (!date) return "No confirmed date yet";
  return `Earnings ${fmtEarningsDate(date)}, ${confirmation === "confirmed" ? "confirmed" : "estimated"}`;
}

/** A company listed under two share classes in the S&P 500 labels each card with its class (both share one company name). */
export const SHARE_CLASS: Record<string, string> = {
  GOOGL: "Class A", GOOG: "Class C", FOXA: "Class A", FOX: "Class B", NWSA: "Class A", NWS: "Class B",
};
