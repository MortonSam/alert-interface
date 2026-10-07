import { fmtIsoDateTime } from "@/lib/freshness";
/**
 * The one sentence under each Discover row: why this stock is in this section.
 *
 * Every clause is built from a field the API already returns for that section
 * (the same fields the old cards read), so a row says nothing a card did not.
 * The earnings clause always carries its confirmation level, with the source in
 * parentheses. No clause is cut short: the row wraps instead.
 */
import type {
  EarningsOutcome,
  JustReportedItem,
  LatestPickItem,
  ReportingSoonItem,
  SuggestionItem,
  UnusuallyActiveItem,
} from "@/lib/api";
import { CALENDAR_SOURCE, checkedPhrase, earningsSourceNote, fmtEarningsDate } from "@/lib/earningsSource";
import { discoverRvTier } from "@/lib/encodings/rvTier";
import { volRegime } from "@/lib/encodings/volRegime";

/** Whole calendar days from today (viewer's zone) to an ISO date. */
export function daysUntil(dateStr: string, now: Date = new Date()): number {
  const [y, m, d] = dateStr.split("-").map(Number);
  const target = new Date(y, m - 1, d);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

/** "Beat 7 of 8" reads as "beat 7 of 8" after a semicolon; "IV rich" and "S&P" keep their capitals. */
function lowerFirst(s: string): string {
  return /^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s;
}

function upperFirst(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function join(clauses: (string | null | undefined)[]): string {
  const parts = clauses.filter((c): c is string => !!c && c.trim().length > 0).map((c) => c.trim());
  return upperFirst(parts.map((p, i) => (i === 0 ? p : lowerFirst(p))).join("; "));
}

/** The vol regime chip's word, as a clause. iv_fair was never marked on a card and is not here either. */
export function ivClause(regime: string | null | undefined, note?: string | null): string | null {
  if (note) return note;                       // one session dominates the window: the API sends the note instead of a regime
  const v = regime && regime !== "iv_fair" ? volRegime(regime) : null;
  return v ? v.label.replace(/^IV (\w+)/, (_, w: string) => `IV ${w.toLowerCase()}`) : null;
}

/**
 * What kind of source confirmed a date, from the type prefix the calendar refresh writes into the note
 * (backend report_announcements / earnings_calendar). Never the headline or the filing date that follow it.
 */
export const CONFIRMED_KIND = {
  pressRelease: "company press release",   // "confirmed: press release via Finnhub news <date>: <headline>"
  secFiling: "SEC filing",                 // "confirmed: 8-K Item 7.01 filed <date>"
  calendars: "Finnhub and Yahoo Finance agree",   // AGREEMENT_NOTE: two calendars on the same day
  company: "company announcement",         // a company confirmation with no recorded evidence, or a note of no known type
} as const;

export function confirmedKind(note: string | null | undefined): string {
  const body = (note ?? "").replace(/^confirmed:\s*/i, "").trim();
  if (/^press release\b/i.test(body)) return CONFIRMED_KIND.pressRelease;
  if (/^8-K\b/i.test(body)) return CONFIRMED_KIND.secFiling;
  if (/^Finnhub and Yahoo Finance agree$/i.test(body)) return CONFIRMED_KIND.calendars;
  return CONFIRMED_KIND.company;
}

/** The level and its evidence: "confirmed, company press release", "estimated, Finnhub, checked today". */
function levelNote(
  confirmation: string | null | undefined,
  note: string | null | undefined,
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  now: Date,
): string {
  if (confirmation === "confirmed") return `confirmed, ${confirmedKind(note)}`;
  const level = confirmation === "expected_unconfirmed" ? "not confirmed" : "estimated";
  return `${level}, ${earningsSourceNote(source, checkedAt, now)}`;
}

/** A ticker the calendar left without a date: "No confirmed date yet (Finnhub, checked today)". */
export function noDateClause(checkedAt: string | null | undefined, now: Date = new Date()): string {
  return checkedAt
    ? `No confirmed date yet (${CALENDAR_SOURCE}, ${checkedPhrase(checkedAt, now)})`
    : "No confirmed date yet (not yet checked)";
}

/** The next-earnings clause for a section whose reason is not the calendar. */
export function earningsClause(
  date: string | null | undefined,
  source: string | null | undefined,
  checkedAt: string | null | undefined,
  confirmation: string | null | undefined,
  note: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!date) return noDateClause(checkedAt, now);
  const lvl = levelNote(confirmation, note, source, checkedAt, now);
  if (confirmation === "confirmed") return `reports ${fmtEarningsDate(date)} (${lvl})`;
  if (confirmation === "expected_unconfirmed") return `expected to report around ${fmtEarningsDate(date)} (${lvl})`;
  return `reports around ${fmtEarningsDate(date)} (${lvl})`;
}

function whenPhrase(days: number): string {
  const d = Math.max(days, 0);
  return d === 0 ? "today" : d === 1 ? "tomorrow" : `in ${d} days`;
}

/** The calendar: "Reports tomorrow (confirmed, company press release); beat 7 of 8, averaging +3.1% ...". */
export function reportingSoonSentence(item: ReportingSoonItem, now: Date = new Date()): string {
  const days = daysUntil(item.earnings_date, now);
  const lvl = levelNote(item.confirmation, item.confirmation_note, item.source, item.checked_at, now);
  const lead = item.confirmation === "expected_unconfirmed"
    ? `Expected to report ${whenPhrase(days)} (${lvl})`
    : `Reports ${whenPhrase(days)} (${lvl})`;
  return join([lead, item.insight, ivClause(item.vol_regime, (item as { iv_rv_note?: string | null }).iv_rv_note)]);
}

/** Every outcome the API can send has words; "unknown" says so rather than guessing. */
export const OUTCOME_LEAD: Record<EarningsOutcome, string> = {
  beat: "Beat estimates",
  miss: "Missed estimates",
  meet: "Met estimates",
  unknown: "Reported; beat or miss not recorded",
};

export function fmtMove(pct: number): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

/** The results: "Beat estimates; moved -6.3% on the 1-day reaction; its typical beat moves +2.7%". */
export function justReportedSentence(item: JustReportedItem): string {
  const move = item.insight
    ?? (item.pct_change_1d != null ? `moved ${fmtMove(item.pct_change_1d)} on the 1-day reaction` : null);
  return join([OUTCOME_LEAD[item.outcome] ?? OUTCOME_LEAD.unknown, move, ivClause(item.vol_regime)]);
}

/** Suggestion score: the most distinctive stored stat, then the next earnings date and its level. */
export function suggestionSentence(item: SuggestionItem, now: Date = new Date()): string {
  return join([
    item.insight,
    earningsClause(item.earnings_date, item.earnings_source, item.earnings_checked_at, item.earnings_confirmation, item.earnings_note, now),
    ivClause(item.vol_regime, (item as { iv_rv_note?: string | null }).iv_rv_note),
  ]);
}

/**
 * The tape: the rank and the word the API admitted it with (discover_rv_tier), then the IV spread from
 * the stored blurb. The blurb's own rank part uses the general scale, so it is not repeated.
 */
export function unusuallyActiveSentence(item: UnusuallyActiveItem, now: Date = new Date()): string {
  const tier = discoverRvTier(item.rv_rank);   // the API's 85/93 cutoffs; item.tier is the same word
  const lead = `RV rank ${Math.round(item.rv_rank)}, ${tier.label} for this stock`;
  const insight = item.insight ?? "";
  const iv = item.iv_rv_note ?? (insight.startsWith("RV rank") ? null : insight.split(" · ")[0] || ivClause(item.vol_regime));
  return join([
    lead,
    iv,
    earningsClause(item.earnings_date, item.earnings_source, item.earnings_checked_at, item.earnings_confirmation, item.earnings_note, now),
  ]);
}

function fmtPrice(n: number): string {
  return `$${n.toFixed(2)}`;
}

/** From the ledger: "Bullish pick (Long call), entered at $182.10, now $190.00 (stock +4.3%); open". */
export function latestPickSentence(pick: LatestPickItem): string {
  const dir = pick.picked_direction === "bullish" ? "Bullish" : "Bearish";
  let lead = `${dir} pick${pick.strategy ? ` (${pick.strategy})` : ""}, entered at ${fmtPrice(pick.entry_price)}`;
  if (pick.current_price != null) {
    lead += `, now ${fmtPrice(pick.current_price)}`;
    if (pick.unrealized_move_pct != null) lead += ` (stock ${fmtMove(pick.unrealized_move_pct)})`;
    const asOf = fmtIsoDateTime(pick.price_as_of);
    if (asOf) lead += ` as of ${asOf}`;
  } else if (pick.quote_reason) {
    lead += ` (no current price: ${pick.quote_reason})`;
  }
  const status = pick.status === "closed" && pick.option_pnl_pct != null
    ? `closed, option P&L ${pick.option_pnl_pct > 0 ? "+" : ""}${pick.option_pnl_pct.toFixed(0)}%`
    : pick.status;
  return join([lead, status]);
}
