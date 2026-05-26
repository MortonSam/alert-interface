"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Ticker } from "@/lib/api";

export function TickerGrid() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.tickers
      .list()
      .then(setTickers)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <section className="mt-10">
        <div className="h-6 w-24 bg-muted rounded animate-pulse mb-4" />
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="rounded-lg border bg-card p-4 animate-pulse">
              <div className="h-6 bg-muted rounded w-14 mb-2" />
              <div className="h-3 bg-muted rounded w-full mb-1" />
              <div className="h-3 bg-muted rounded w-3/4 mb-3" />
              <div className="h-3 bg-muted rounded w-1/2" />
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="mt-10">
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          Failed to load tickers: {error}
        </div>
      </section>
    );
  }

  if (tickers.length === 0) {
    return (
      <section className="mt-10">
        <div className="rounded-lg border bg-card px-6 py-10 text-center text-sm text-muted-foreground">
          No tickers found. Seed some with <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">seed_ticker.py</code> to get started.
        </div>
      </section>
    );
  }

  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold mb-4">
        Tickers{" "}
        <span className="text-muted-foreground font-normal text-sm">({tickers.length})</span>
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        {tickers.map((ticker) => (
          <Link
            key={ticker.id}
            href={`/tickers/${ticker.symbol}`}
            className="rounded-lg border bg-card p-4 transition-colors hover:bg-accent hover:border-border"
          >
            <div className="text-xl font-bold tracking-tight">{ticker.symbol}</div>
            {ticker.name && (
              <div className="text-xs text-muted-foreground mt-1 line-clamp-2 leading-snug">
                {ticker.name}
              </div>
            )}
            <div className="mt-3 space-y-0.5">
              {ticker.sector && (
                <div className="text-xs text-muted-foreground line-clamp-1">{ticker.sector}</div>
              )}
              {ticker.industry && (
                <div className="text-xs text-muted-foreground line-clamp-1">{ticker.industry}</div>
              )}
              {ticker.exchange && (
                <div className="text-xs font-medium text-foreground/60 mt-1">{ticker.exchange}</div>
              )}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
