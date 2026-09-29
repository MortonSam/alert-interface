/**
 * The next-earnings line: the date, where it came from, and when that source was last asked.
 *
 * "Next earnings Oct 29 (Finnhub, checked today)". Every part is rendered from
 * API fields (next_earnings_date, next_earnings_source, next_earnings_checked_at
 * on a ticker; earnings_date, source, checked_at on a Discover card). A ticker
 * with no date still says when it was checked, so "none" is a finding, not a gap.
 */
const SOURCE_LABELS: Record<string, string> = {
  finnhub: "Finnhub",
  yfinance: "Yahoo Finance",
  edgar: "EDGAR",
  manual: "entered by hand",
};

export function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_LABELS[source] ?? source;
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

/**
 * The line for a ticker the calendar left without a future date. The calendar refresh is the only
 * writer of earnings_checked_at and it asks Finnhub, so the source it names is Finnhub.
 */
export const CALENDAR_SOURCE = "Finnhub";
export function noDateLine(checkedAt: string | null | undefined): string {
  return checkedAt ? `No confirmed date yet (${CALENDAR_SOURCE}, ${checkedOn(checkedAt)})` : "No confirmed date yet (not yet checked)";
}

/** The full line for a ticker header. */
export function nextEarningsLine(
  date: string | null | undefined,
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  now: Date = new Date(),
): string {
  const checked = checkedPhrase(checkedAt, now);
  if (!date) return noDateLine(checkedAt);
  const src = sourceLabel(source);
  return `Next earnings ${fmtEarningsDate(date)} (${src ? `${src}, ` : ""}${checked})`;
}

/** The whole card note: the dated line, or the no-date line, never blank. */
export function cardEarningsNote(
  date: string | null | undefined,
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!date) return noDateLine(checkedAt);
  return `Next earnings ${fmtEarningsDate(date)} \u00B7 ${earningsSourceNote(source, checkedAt, now)}`;
}

/** The short form under a Discover card: "Finnhub, checked today". */
export function earningsSourceNote(
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  now: Date = new Date(),
): string {
  const src = sourceLabel(source);
  const checked = checkedPhrase(checkedAt, now);
  return src ? `${src}, ${checked}` : checked;
}
