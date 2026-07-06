"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import Link from "next/link";
import { api, type BatchQuote, type SystemStatus, type Ticker } from "@/lib/api";

const PAGE_SIZE = 24;

function fmtAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function isStale(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() > 3 * 24 * 60 * 60 * 1000;
}

function fmtMcap(n: number | null): string {
  if (!n) return "";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString()}`;
}

function fmtDate(d: string | null): string {
  if (!d) return "";
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

type SortKey = "market_cap" | "symbol" | "name" | "next_earnings";

function getPageNums(current: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const out: (number | "…")[] = [1];
  if (current > 3) out.push("…");
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
    out.push(i);
  }
  if (current < total - 2) out.push("…");
  out.push(total);
  return out;
}

export function TickerGrid() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sector, setSector] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("market_cap");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.tickers
      .list()
      .then(setTickers)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
    api.system.status().then(setSystemStatus).catch(() => null);
  }, []);

  // Debounce search input
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  // Reset to page 1 on filter/sort change
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, sector, sort]);

  // Sector counts from full (unfiltered) list
  const sectorCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of tickers) {
      if (t.sector) m.set(t.sector, (m.get(t.sector) ?? 0) + 1);
    }
    return m;
  }, [tickers]);

  const sectors = useMemo(() => [...sectorCounts.keys()].sort(), [sectorCounts]);

  // Filtered + sorted list
  const filtered = useMemo(() => {
    let list = tickers;
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase();
      list = list.filter(
        (t) =>
          t.symbol.toLowerCase().includes(q) ||
          (t.name ?? "").toLowerCase().includes(q)
      );
    }
    if (sector) {
      list = list.filter((t) => t.sector === sector);
    }
    return [...list].sort((a, b) => {
      switch (sort) {
        case "symbol":
          return a.symbol.localeCompare(b.symbol);
        case "name":
          return (a.name ?? "").localeCompare(b.name ?? "");
        case "next_earnings": {
          const dateA = a.next_earnings_date ?? "9999-99-99";
          const dateB = b.next_earnings_date ?? "9999-99-99";
          return dateA < dateB ? -1 : dateA > dateB ? 1 : 0;
        }
        default: // market_cap desc
          return (b.market_cap ?? 0) - (a.market_cap ?? 0);
      }
    });
  }, [tickers, debouncedSearch, sector, sort]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paginated = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const isFiltered = !!debouncedSearch || !!sector || sort !== "market_cap";

  // ── Batch quote fetch for the current page ──────────────────────────────────
  const [quotes, setQuotes] = useState<Map<string, BatchQuote>>(new Map());
  const [quotesLoading, setQuotesLoading] = useState(false);
  const pageSymbols = paginated.map((t) => t.symbol).join(",");

  useEffect(() => {
    if (!pageSymbols) return;
    const syms = pageSymbols.split(",");
    setQuotesLoading(true);
    api.tickers
      .quotes(syms)
      .then((data) => {
        const m = new Map<string, BatchQuote>();
        for (const q of data) m.set(q.symbol, q);
        setQuotes(m);
      })
      .catch(() => setQuotes(new Map()))
      .finally(() => setQuotesLoading(false));
  }, [pageSymbols]);

  const clearFilters = useCallback(() => {
    setSearch("");
    setDebouncedSearch("");
    setSector(null);
    setSort("market_cap");
  }, []);

  if (loading) {
    return (
      <section className="mt-8 space-y-4">
        <div className="h-9 bg-muted rounded animate-pulse w-full" />
        <div className="flex gap-2 flex-wrap">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-7 w-28 bg-muted rounded-full animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {Array.from({ length: 18 }).map((_, i) => (
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
      <section className="mt-8">
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          Failed to load tickers: {error}
        </div>
      </section>
    );
  }

  if (tickers.length === 0) {
    return (
      <section className="mt-8">
        <div className="rounded-lg border bg-card px-6 py-10 text-center text-sm text-muted-foreground">
          No tickers found. Seed some with{" "}
          <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">seed_ticker.py</code>{" "}
          to get started.
        </div>
      </section>
    );
  }

  return (
    <section className="mt-8 space-y-4">
      {/* Freshness indicator */}
      <div className="flex justify-end items-center gap-2">
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-success" />
          Prices live
        </span>
        {systemStatus?.last_refreshed_at && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full ${
              isStale(systemStatus.last_refreshed_at)
                ? "bg-amber-500/10 text-amber-500"
                : "text-muted-foreground"
            }`}
          >
            Reference data {fmtAgo(systemStatus.last_refreshed_at)}
          </span>
        )}
      </div>

      {/* Search + Sort */}
      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search symbol or name…"
          className="flex-1 min-w-[200px] h-9 rounded-md border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="h-9 rounded-md border bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="market_cap">Market Cap ↓</option>
          <option value="symbol">Symbol A–Z</option>
          <option value="name">Name A–Z</option>
          <option value="next_earnings">Next Earnings</option>
        </select>
      </div>

      {/* Sector pills */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setSector(null)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            sector === null
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-accent"
          }`}
        >
          All <span className="opacity-60">({tickers.length})</span>
        </button>
        {sectors.map((s) => (
          <button
            key={s}
            onClick={() => setSector(sector === s ? null : s)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              sector === s
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-accent"
            }`}
          >
            {s} <span className="opacity-60">({sectorCounts.get(s)})</span>
          </button>
        ))}
      </div>

      {/* Result count + clear */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Showing{" "}
          <span className="font-medium text-foreground">
            {filtered.length === tickers.length
              ? tickers.length
              : `${filtered.length} of ${tickers.length}`}
          </span>{" "}
          tickers
        </span>
        {isFiltered && (
          <button
            onClick={clearFilters}
            className="hover:text-foreground underline underline-offset-2"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <div className="rounded-lg border bg-card px-6 py-12 text-center">
          <p className="text-sm text-muted-foreground mb-3">
            No tickers match your filters.
          </p>
          <button onClick={clearFilters} className="text-sm text-primary hover:underline">
            Clear filters
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {paginated.map((ticker) => {
            const q = quotes.get(ticker.symbol);
            const hasQuote = q && q.price != null;
            return (
              <Link
                key={ticker.id}
                href={`/tickers/${ticker.symbol}`}
                className="rounded-lg border bg-card p-4 transition-colors hover:bg-accent hover:border-border flex flex-col gap-1 min-h-[96px]"
              >
                {/* Header: Symbol + Price */}
                <div className="flex items-start justify-between gap-1">
                  <span className="text-xl font-bold tracking-tight leading-none">
                    {ticker.symbol}
                  </span>
                  <div className="text-right shrink-0">
                    {quotesLoading && !hasQuote ? (
                      <div className="inline-block w-14 h-5 bg-muted rounded animate-pulse" />
                    ) : hasQuote ? (
                      <span className="font-mono text-sm font-semibold tabular-nums">
                        ${q.price!.toFixed(2)}
                      </span>
                    ) : (
                      <span className="font-mono text-sm text-muted-foreground">—</span>
                    )}
                    {/* Day change % */}
                    {hasQuote && q.change_pct != null ? (
                      <div
                        className={`font-mono text-xs tabular-nums ${
                          q.change_pct >= 0 ? "text-success" : "text-destructive"
                        }`}
                      >
                        {q.change_pct >= 0 ? "+" : ""}
                        {q.change_pct.toFixed(2)}%
                      </div>
                    ) : quotesLoading && !hasQuote ? (
                      <div className="inline-block w-10 h-3.5 bg-muted rounded animate-pulse mt-0.5" />
                    ) : null}
                  </div>
                </div>

                {/* Company name */}
                {ticker.name && (
                  <div className="text-xs text-muted-foreground line-clamp-2 leading-snug">
                    {ticker.name}
                  </div>
                )}

                {/* Footer: Sector + Market Cap + Earnings */}
                <div className="mt-auto pt-1 space-y-0.5">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    {ticker.sector && (
                      <span className="line-clamp-1">{ticker.sector}</span>
                    )}
                    {ticker.market_cap ? (
                      <span className="shrink-0">{fmtMcap(ticker.market_cap)}</span>
                    ) : null}
                  </div>
                  {ticker.next_earnings_date && (
                    <div className="text-xs font-medium text-foreground/70">
                      Earnings {fmtDate(ticker.next_earnings_date)}
                    </div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 pt-2 flex-wrap">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
            className="px-3 py-1.5 rounded text-sm border hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ← Prev
          </button>
          {getPageNums(safePage, totalPages).map((p, i) =>
            p === "…" ? (
              <span key={`ell-${i}`} className="px-2 text-sm text-muted-foreground select-none">
                …
              </span>
            ) : (
              <button
                key={p}
                onClick={() => setPage(p as number)}
                className={`px-3 py-1.5 rounded text-sm border transition-colors ${
                  safePage === p
                    ? "bg-primary text-primary-foreground border-primary"
                    : "hover:bg-accent"
                }`}
              >
                {p}
              </button>
            )
          )}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
            className="px-3 py-1.5 rounded text-sm border hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next →
          </button>
        </div>
      )}
    </section>
  );
}
