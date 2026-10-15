import Link from "next/link";
import type { Ticker, TickerExit } from "@/lib/api";

import { fmtDate as fmtOneDate, fmtDateTime as fmtOneDateTime, axisDay, axisTime } from "@/lib/dates";
/** The ticker page for a stock that no longer trades and has no successor (backend services/ticker_exits): the stored line, and the
 * last stored close with its own date when one is stored. No trade builder, market value, catalysts, earnings line or Ask Ivy. */
export function NoLongerTrades({ ticker, exit }: { ticker: Pick<Ticker, "symbol" | "name">; exit: TickerExit }) {
  return (
    <main className="min-h-screen p-4 sm:p-8" data-state="no-longer-trades">
      <div className="max-w-6xl mx-auto">
        <Link href="/" className="tap text-sm text-muted-foreground hover:text-foreground transition-colors">
          ← All tickers
        </Link>
        <div id="overview" className="mt-6">
          <h1 className="text-display font-bold font-display">{ticker.symbol}</h1>
          {ticker.name && <p className="text-xl text-muted-foreground mt-2">{ticker.name}</p>}
        </div>
        <p className="mt-8 text-lg max-w-2xl" data-testid="exit-line">{exit.line}</p>
        {exit.last_close != null && exit.last_close_date && (
          <p className="mt-3 font-mono text-xs text-muted-foreground" data-testid="exit-last-close">
            Last stored close ${exit.last_close.toFixed(2)} on {longDate(exit.last_close_date)}
          </p>
        )}
      </div>
    </main>
  );
}

/** "2026-08-04" -> "Aug 4, 2026", the one date format (lib/dates), read as a calendar day (no time zone can move it a day). */
export function longDate(iso: string): string {
  return fmtOneDate(iso.slice(0, 10)) ?? iso;
}
