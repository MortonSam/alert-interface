// The one ticker matcher: Build a Trade's picker and the search box in the header use it, so a query
// finds the same names in the same order everywhere.

import type { Ticker } from "@/lib/api";

export const SEARCH_LIMIT = 8;

/** Tickers whose symbol or company name contains the query: exact symbol first, then symbol prefix, then market cap. */
export function matchTickers(tickers: Ticker[], query: string, limit = SEARCH_LIMIT): Ticker[] {
  if (!query.trim()) return [];
  const q = query.trim().toLowerCase();
  const q2 = query.trim().toUpperCase();
  return tickers
    .filter((t) => t.symbol.toLowerCase().includes(q) || (t.name ?? "").toLowerCase().includes(q))
    .sort((a, b) => {
      if (a.symbol === q2 && b.symbol !== q2) return -1;
      if (b.symbol === q2 && a.symbol !== q2) return 1;
      const aStarts = a.symbol.startsWith(q2);
      const bStarts = b.symbol.startsWith(q2);
      if (aStarts && !bStarts) return -1;
      if (!aStarts && bStarts) return 1;
      return (b.market_cap ?? 0) - (a.market_cap ?? 0);
    })
    .slice(0, limit);
}

/** Where Enter goes: the top match's page, or nowhere when nothing matches. */
export function tickerPath(matches: Ticker[]): string | null {
  return matches.length ? `/tickers/${matches[0].symbol}` : null;
}
