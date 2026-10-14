// The ticker page header: which chart period opens, the change the headline shows for the selected period, its color,
// and the line that says what the price is (a delayed quote, a last trade or a close) with its own date and time.
// Every figure comes from the quote or the chart the API returned; nothing is estimated here.
import type { MarketSession, MarketSessionDay, TickerChart, TickerQuote } from "@/lib/api";
import { fmtDay, fmtDayUnix, fmtTimeUnix, nyClock } from "@/lib/tickerDates";

export const CHART_PERIODS = ["1d", "7d", "1mo", "3mo", "6mo", "1y", "5y"] as const;
export type ChartPeriod = (typeof CHART_PERIODS)[number];
export const PERIOD_LABELS: Record<ChartPeriod, string> = { "1d": "1D", "7d": "1W", "1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1Y", "5y": "5Y" };

/** The NYSE session (backend services/market_status) that covers `nowMs`'s New York date: today's, or the next one when the
 * answer was read the day before. Null when the answer covers neither, so the page makes no claim about the market. */
export function sessionOn(session: MarketSession | null | undefined, nowMs: number): MarketSessionDay | null {
  if (!session) return null;
  const today = nyClock(nowMs).date;
  return [session.today, session.next].find((d) => d?.date === today) ?? null;
}

/** A chart answer with bars to draw. */
export function hasBars(chart: Pick<TickerChart, "history" | "history_state"> | null | undefined): boolean {
  return !!chart && (chart.history_state == null || chart.history_state === "ok") && chart.history.length > 0;
}

/** The period the header opens on: 1D when it has intraday bars, otherwise the shortest period that does. Probes in order
 * and stops at the first answer with bars; null when none has any. */
export async function openingPeriod(fetchChart: (p: ChartPeriod) => Promise<TickerChart>): Promise<{ period: ChartPeriod; chart: TickerChart; skipped: ChartPeriod[] } | null> {
  const skipped: ChartPeriod[] = [];
  for (const p of CHART_PERIODS) {
    try {
      const chart = await fetchChart(p);
      if (hasBars(chart)) return { period: p, chart, skipped };
    } catch { /* an unanswered period counts as empty */ }
    skipped.push(p);
  }
  return null;
}

export type Direction = "up" | "down" | "flat";

export interface PeriodChange {
  change: number;        // dollars
  pct: number;           // percent units
  direction: Direction;  // from the change as printed (2 decimals), so the color never disagrees with the sign shown
  since: string;         // "since the previous close" | "since Oct 5, 2026"
}

/** The headline change for a period. 1D is the quote's own change against the previous close, as the API sent it; every other
 * period is the quote's price against the period's first close (the chart's start_price, dated by its first bar). Null when
 * either side is missing. */
export function periodChange(
  period: ChartPeriod,
  quote: Pick<TickerQuote, "price" | "change" | "change_pct"> | null | undefined,
  chart: Pick<TickerChart, "start_price" | "history"> | null | undefined,
): PeriodChange | null {
  if (!quote || quote.price == null) return null;
  let change: number, pct: number, since: string;
  if (period === "1d") {
    if (quote.change == null || quote.change_pct == null) return null;
    change = quote.change; pct = quote.change_pct; since = "since the previous close";
  } else {
    const start = chart?.start_price;
    const first = chart?.history?.[0]?.date;
    const day = fmtDay(first ?? null);
    if (start == null || start === 0 || !day) return null;
    change = quote.price - start; pct = (change / start) * 100; since = `since ${day}`;
  }
  const shown = Number(change.toFixed(2));
  return { change, pct, since, direction: shown > 0 ? "up" : shown < 0 ? "down" : "flat" };
}

/** "+1.93 (+3.26%)" */
export function fmtChange(c: PeriodChange): string {
  const s = (n: number) => (Number(n.toFixed(2)) > 0 ? "+" : "");
  return `${s(c.change)}${c.change.toFixed(2)} (${s(c.pct)}${c.pct.toFixed(2)}%)`;
}

/** One color per direction, read by the headline number and the chart line alike. */
export const DIRECTION_STYLE: Record<Direction, { text: string; stroke: string }> = {
  up: { text: "text-success", stroke: "hsl(var(--success))" },
  down: { text: "text-destructive", stroke: "hsl(var(--destructive))" },
  flat: { text: "text-foreground", stroke: "hsl(var(--foreground))" },
};

export type QuoteTimeState = "delayed_session" | "closed" | "session_no_live";

/** The line under the price, from the quote's own basis and time, the New York clock at `nowMs` and the exchange's session for
 * that day from the backend calendar (holidays and 1 p.m. closes included):
 *  - a delayed quote from today while the session runs: "Delayed 15 minutes. Last trade at 1:02 PM ET on Oct 13, 2026."
 *  - outside the session, or on a day with none: "Market closed. Showing the close at 4:00 PM ET on Oct 13, 2026." (or "the last trade")
 *  - inside the session without a delayed quote from today, or with no session answer for today: the time alone, no claim about
 *    the market. Null when the quote has no time. */
export function quoteTimeLine(
  quote: Pick<TickerQuote, "timestamp" | "quote_basis" | "delay_minutes"> | null | undefined,
  nowMs: number,
  session: MarketSession | null | undefined,
): { state: QuoteTimeState; text: string } | null {
  if (!quote || quote.timestamp == null) return null;
  const day = fmtDayUnix(quote.timestamp), time = fmtTimeUnix(quote.timestamp);
  if (!day || !time) return null;
  const what = quote.quote_basis === "close" ? "the close" : "the last trade";
  const plain = { state: "session_no_live" as const, text: `Showing ${what} at ${time} on ${day}.` };
  const s = sessionOn(session, nowMs);
  if (!s) return plain;
  const inSession = s.is_trading_day && !!s.open_at && !!s.close_at && Date.parse(s.open_at) <= nowMs && nowMs < Date.parse(s.close_at);
  const tradedToday = nyClock(quote.timestamp * 1000).date === nyClock(nowMs).date;
  if (inSession && tradedToday && quote.quote_basis === "delayed") {
    const delay = quote.delay_minutes != null && quote.delay_minutes > 0 ? `Delayed ${quote.delay_minutes} minutes.` : "Delayed quote.";
    return { state: "delayed_session", text: `${delay} Last trade at ${time} on ${day}.` };
  }
  if (!inSession) return { state: "closed", text: `Market closed. Showing ${what} at ${time} on ${day}.` };
  return plain;
}
