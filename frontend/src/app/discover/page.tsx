"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import DiscoverCard from "@/components/DiscoverCard";
import { SectionKicker } from "@/components/SectionKicker";
import {
  api,
  type ReportingSoonItem,
  type JustReportedItem,
  type SuggestionItem,
  type UnusuallyActiveItem,
  type BatchQuote,
  type LatestPickItem,
  type HealthStatus,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

function fmtQuoteTime(unix: number | null | undefined): string {
  if (unix == null) return "";
  const d = new Date(unix * 1000);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function daysUntil(dateStr: string): number {
  const [y, m, d] = dateStr.split("-").map(Number);
  const target = new Date(y, m - 1, d);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function fmtPrice(n: number | null | undefined): string {
  return n == null ? "" : `$${n.toFixed(2)}`;
}

/** Map days-until-earnings → color classes for the proximity tag. */
function earningsUrgency(days: number): { bg: string; text: string } {
  if (days <= 1) return { bg: "bg-primary/10", text: "text-primary" };       // orange — imminent
  if (days <= 3) return { bg: "bg-warning/10", text: "text-warning" };       // amber — soon
  return { bg: "bg-muted", text: "text-muted-foreground" };                  // neutral — further out
}

// ── Skeletons ────────────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="rounded-xl border border-border/60 p-4 animate-pulse">
      <div className="flex items-start justify-between mb-2">
        <div className="h-5 w-16 bg-muted rounded" />
        <div className="h-4 w-14 bg-muted rounded" />
      </div>
      <div className="h-3.5 w-28 bg-muted rounded mb-3" />
      <div className="h-6 w-20 bg-muted rounded-full" />
    </div>
  );
}

function SectionSkeleton() {
  return (
    <div className="border-t border-border py-10">
      <div className="mb-4">
        <div className="h-3 w-32 bg-muted rounded mb-3 animate-pulse" />
        <div className="h-5 w-48 bg-muted rounded mb-1 animate-pulse" />
        <div className="h-3 w-64 bg-muted rounded animate-pulse" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

const LIMIT = 12;

export default function DiscoverPage() {
  const [reportingSoon, setReportingSoon] = useState<{
    items: ReportingSoonItem[];
    total: number;
  } | null>(null);
  const [justReported, setJustReported] = useState<{
    items: JustReportedItem[];
    total: number;
  } | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionItem[] | null>(null);
  const [unusuallyActive, setUnusuallyActive] = useState<UnusuallyActiveItem[] | null>(null);
  const [latestPick, setLatestPick] = useState<LatestPickItem | null | undefined>(undefined);
  const [quotes, setQuotes] = useState<Map<string, BatchQuote>>(new Map());
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  // Hide AI suggestions when every pick duplicates "Reporting soon"
  const reportingSoonSymbols = new Set(
    reportingSoon?.items.map((i) => i.symbol) ?? [],
  );
  const suggestionsAddValue =
    !loading &&
    suggestions != null &&
    suggestions.some((s) => !reportingSoonSymbols.has(s.symbol));

  function loadDiscover() {
    setLoading(true);
    setFetchError(false);
    Promise.all([
      api.discover.reportingSoon(7, LIMIT),
      api.discover.justReported(5, LIMIT),
      api.discover.suggestions(5),
      api.discover.unusuallyActive(LIMIT),
      api.discover.latestPick().catch(() => ({ pick: null })),
    ]).then(([rs, jr, sg, ua, lp]) => {
      setReportingSoon(rs);
      setJustReported(jr);
      setSuggestions(sg.items);
      setUnusuallyActive(ua.items);
      setLatestPick(lp.pick);
      setLoading(false);

      // Batch-fetch quotes for all displayed symbols
      const allSymbols = [
        ...rs.items.map((i) => i.symbol),
        ...jr.items.map((i) => i.symbol),
        ...sg.items.map((i) => i.symbol),
        ...ua.items.map((i) => i.symbol),
      ];
      if (lp.pick) allSymbols.push(lp.pick.symbol);
      const unique = [...new Set(allSymbols)];
      if (unique.length > 0) {
        api.tickers
          .quotes(unique)
          .then((bq) => {
            const map = new Map<string, BatchQuote>();
            for (const q of bq) map.set(q.symbol, q);
            setQuotes(map);
          })
          .catch(() => {});
      }
    }).catch(() => {
      setLoading(false);
      setFetchError(true);
    });
  }

  useEffect(() => {
    loadDiscover();
    api.system.health().then(setHealth).catch(() => {});
  }, []);

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-10">
          <div className="flex items-center gap-3 mb-1">
            <Link
              href="/"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              &larr; Home
            </Link>
          </div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-foreground">
            Discover
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            What&apos;s worth researching across your universe right now.
          </p>
          {(health?.last_refreshed_at || quotes.size > 0) && (
            <p className="text-[11px] font-mono text-muted-foreground/60 mt-1.5">
              {health?.last_refreshed_at && <>Data as of {timeAgo(health.last_refreshed_at)}</>}
              {health?.last_refreshed_at && quotes.size > 0 && " · "}
              {quotes.size > 0 && (() => {
                const ts = [...quotes.values()].map(q => q.timestamp).filter(Boolean);
                const latest = ts.length > 0 ? Math.max(...(ts as number[])) : null;
                return latest ? <>Quotes as of {fmtQuoteTime(latest)}</> : null;
              })()}
            </p>
          )}
        </div>

        {/* ── Fetch error ──────────────────────────────── */}
        {fetchError && (
          <div className="border-t border-border py-10 space-y-4">
            <p className="text-sm text-muted-foreground">
              Couldn&apos;t load Discover right now.
            </p>
            <button
              onClick={loadDiscover}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* ── 01 · Ivy's Pick ──────────────────────────── */}
        {!loading && latestPick && (
          <section className="border-t border-border py-10">
            <SectionKicker index="01" label="From the ledger" />
            <Link
              href="/ivy/trades"
              className="flex items-center gap-3 hover:opacity-80 transition-opacity group"
            >
              <span className="font-display text-sm font-bold text-foreground">
                {latestPick.symbol}
              </span>
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide ${
                latestPick.picked_direction === "bullish"
                  ? "bg-success/10 text-success"
                  : "bg-destructive/10 text-destructive"
              }`}>
                {latestPick.picked_direction === "bullish" ? "Bullish" : "Bearish"}
              </span>
              {latestPick.strategy && (
                <span className="text-[11px] text-muted-foreground hidden sm:inline">
                  {latestPick.strategy}
                </span>
              )}
              <span className="text-xs text-muted-foreground font-mono">
                {fmtPrice(latestPick.entry_price)}
              </span>
              {latestPick.current_price != null && (
                <>
                  <span className="text-[11px] text-muted-foreground">{"\u2192"}</span>
                  <span className="text-xs font-mono text-muted-foreground">
                    {fmtPrice(latestPick.current_price)}
                  </span>
                </>
              )}
              {latestPick.unrealized_move_pct != null && (
                <span className={`text-xs font-mono font-semibold ${
                  latestPick.unrealized_move_pct === 0 ? "text-muted-foreground" :
                  (latestPick.picked_direction === "bullish" ? latestPick.unrealized_move_pct > 0 : latestPick.unrealized_move_pct < 0) ? "text-success" : "text-destructive"
                }`}>
                  {latestPick.unrealized_move_pct > 0 ? "+" : ""}{latestPick.unrealized_move_pct.toFixed(1)}%
                </span>
              )}
              {latestPick.status === "closed" && latestPick.option_pnl_pct != null && (
                <span className={`text-[10px] font-semibold ${
                  latestPick.option_pnl_pct >= 0 ? "text-success" : "text-destructive"
                }`}>
                  P&L {latestPick.option_pnl_pct > 0 ? "+" : ""}{latestPick.option_pnl_pct.toFixed(0)}%
                </span>
              )}
              <span className={`ml-auto text-[10px] font-medium rounded-full px-2 py-0.5 ${
                latestPick.status === "open"
                  ? "bg-cool/10 text-cool"
                  : "bg-muted text-muted-foreground"
              }`}>
                {latestPick.status}
              </span>
            </Link>
          </section>
        )}

        {/* ── 02 · Reporting soon ─────────────────────── */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError ? (
          <section className="border-t border-border py-10">
            <SectionKicker index="02" label="The calendar" />
            <h2 className="font-display text-xl font-bold text-foreground">Reporting soon</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Earnings in the next 7 days</p>

            {reportingSoon && reportingSoon.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing reporting in the next 7 days.
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {reportingSoon?.items.map((item) => {
                  const days = daysUntil(item.earnings_date);
                  const q = quotes.get(item.symbol);
                  const urg = earningsUrgency(days);
                  const tagLabel =
                    days <= 0
                      ? "EPS today"
                      : days === 1
                        ? "EPS in 1d"
                        : `EPS in ${days}d`;
                  return (
                    <DiscoverCard
                      key={item.symbol}
                      symbol={item.symbol}
                      name={item.name}
                      price={q?.price != null ? fmtPrice(q.price) : undefined}
                      insight={item.insight}
                      volRegime={item.vol_regime}
                      badge={
                        <span className={`inline-flex items-center gap-1.5 rounded-full ${urg.bg} ${urg.text} px-2.5 py-1 text-[11px] font-semibold tracking-wide`}>
                          <span className="text-[8px]">{"\u25CF"}</span>
                          {tagLabel}
                        </span>
                      }
                    />
                  );
                })}
              </div>
            )}
          </section>
        ) : null}

        {/* ── 03 · Just reported (hidden when empty) ──── */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError && justReported && justReported.items.length === 0 ? null : !fetchError ? (
          <section className="border-t border-border py-10">
            <SectionKicker index="03" label="The results" />
            <h2 className="font-display text-xl font-bold text-foreground">Just reported</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Notable earnings reaction in the last 5 days</p>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {justReported?.items.map((item) => {
                  const move = item.pct_change_1d;
                  const outcomeLabel =
                    item.outcome === "beat"
                      ? "Beat"
                      : item.outcome === "miss"
                        ? "Missed"
                        : item.outcome === "meet"
                          ? "Met"
                          : "\u2014";
                  const moveColor =
                    move != null && move > 0
                      ? "text-success"
                      : move != null && move < 0
                        ? "text-destructive"
                        : "text-muted-foreground";
                  const moveStr =
                    move != null
                      ? `${move > 0 ? "+" : ""}${move.toFixed(1)}%`
                      : "";

                  return (
                    <DiscoverCard
                      key={item.symbol}
                      symbol={item.symbol}
                      name={item.name}
                      price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                      insight={item.insight}
                      volRegime={item.vol_regime}
                      badge={
                        <span className="inline-flex items-center gap-2 rounded-full bg-muted text-foreground px-2.5 py-1 text-[11px] font-semibold tracking-wide">
                          {outcomeLabel}
                          {moveStr && (
                            <span className={moveColor}>{moveStr}</span>
                          )}
                        </span>
                      }
                    />
                  );
                })}
              </div>
          </section>
        ) : null}

        {/* ── 04 · Ivy's Picks (hidden when all picks duplicate Reporting soon) */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError && suggestionsAddValue ? (
          <section className="border-t border-border py-10">
            <SectionKicker index="04" label="From Ivy" />
            <h2 className="font-display text-xl font-bold text-foreground">Ivy&apos;s Picks</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Stocks Ivy thinks are worth a look right now</p>

            {suggestions && suggestions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No standout setups right now.
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {suggestions?.map((item) => (
                  <DiscoverCard
                    key={item.symbol}
                    symbol={item.symbol}
                    name={item.name}
                    price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                    insight={item.insight}
                    volRegime={item.vol_regime}
                  />
                ))}
              </div>
            )}
          </section>
        ) : null}

        {/* ── 05 · Unusually active (hidden when empty) ── */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError && unusuallyActive && unusuallyActive.length > 0 ? (
          <section className="border-t border-border py-10">
            <SectionKicker index="05" label="The tape" />
            <h2 className="font-display text-xl font-bold text-foreground">Unusually active</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Volatility high vs. their own norm</p>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {unusuallyActive.map((item) => {
                const tagLabel = `RV ${Math.round(item.rv_rank)} \u00B7 ${item.tier}`;
                return (
                  <DiscoverCard
                    key={item.symbol}
                    symbol={item.symbol}
                    name={item.name}
                    price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                    insight={item.insight}
                    volRegime={item.vol_regime}
                    badge={
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-muted text-foreground px-2.5 py-1 text-[11px] font-semibold tracking-wide">
                        <span className="text-[8px]">{"\u25CF"}</span>
                        {tagLabel}
                      </span>
                    }
                  />
                );
              })}
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
