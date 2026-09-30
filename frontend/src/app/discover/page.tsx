"use client";

import { JUST_REPORTED_ENABLED } from "@/lib/features";
import { freshnessLine } from "@/lib/freshness";
import { useEffect, useState } from "react";
import Link from "next/link";
import DiscoverRow, { DiscoverRows } from "@/components/DiscoverRow";
import {
  justReportedSentence,
  latestPickSentence,
  reportingSoonSentence,
  suggestionSentence,
  unusuallyActiveSentence,
} from "@/lib/discoverSentences";
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
import { capture } from "@/lib/analytics";

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

function fmtPrice(n: number | null | undefined): string {
  return n == null ? "" : `$${n.toFixed(2)}`;
}

// ── Skeletons ────────────────────────────────────────────────────────────────

function RowSkeleton() {
  return (
    <li className="py-3 animate-pulse sm:grid sm:grid-cols-[18rem_minmax(0,1fr)] sm:gap-x-6">
      <div className="flex items-center gap-2">
        <div className="h-4 w-12 bg-muted rounded" />
        <div className="h-3.5 w-28 bg-muted rounded" />
      </div>
      <div className="h-3.5 w-full max-w-md bg-muted rounded mt-1.5 sm:mt-0" />
    </li>
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
      <DiscoverRows>
        {[1, 2, 3, 4].map((i) => (
          <RowSkeleton key={i} />
        ))}
      </DiscoverRows>
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
      JUST_REPORTED_ENABLED ? api.discover.justReported(5, LIMIT) : Promise.resolve({ items: [], total: 0 }),
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
      capture("discover_viewed");

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

  // Sections are numbered as they render, so a hidden one (Just reported off, no ledger pick, no active names) never leaves a gap.
  let sectionN = 0;
  const nextIndex = () => String(++sectionN).padStart(2, "0");
  return (
    <main className="min-h-screen p-4 sm:p-8">
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
            What&apos;s worth researching across the S&amp;P 500 right now.
          </p>
          {(health?.last_refreshed_at || quotes.size > 0) && (
            <p className="text-[11px] font-mono text-muted-foreground/60 mt-1.5">
              {health?.last_refreshed_at && <>{freshnessLine(timeAgo(health.last_refreshed_at))}</>}
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
            <SectionKicker index={nextIndex()} label="From the ledger" />
            <DiscoverRows>
              <DiscoverRow
                symbol={latestPick.symbol}
                price={quotes.get(latestPick.symbol)?.price != null ? fmtPrice(quotes.get(latestPick.symbol)!.price) : undefined}
                sentence={latestPickSentence(latestPick)}
              />
            </DiscoverRows>
          </section>
        )}

        {/* ── 02 · Reporting soon ─────────────────────── */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError ? (
          <section className="border-t border-border py-10">
            <SectionKicker index={nextIndex()} label="The calendar" />
            <h2 className="font-display text-xl font-bold text-foreground">Reporting soon</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Earnings in the next 7 days</p>

            {reportingSoon && reportingSoon.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing reporting in the next 7 days.
              </p>
            ) : (
              <DiscoverRows>
                {reportingSoon?.items.map((item) => (
                  <DiscoverRow
                    key={item.symbol}
                    symbol={item.symbol}
                    name={item.name}
                    price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                    sentence={reportingSoonSentence(item)}
                  />
                ))}
              </DiscoverRows>
            )}
          </section>
        ) : null}

        {/* ── 03 · Just reported (hidden when empty) ──── */}
        {!JUST_REPORTED_ENABLED ? null : !fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError && justReported && justReported.items.length === 0 ? null : !fetchError ? (
          <section className="border-t border-border py-10">
            <SectionKicker index={nextIndex()} label="The results" />
            <h2 className="font-display text-xl font-bold text-foreground">Just reported</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Earnings reactions in the last 5 days</p>

            <DiscoverRows>
              {justReported?.items.map((item) => (
                <DiscoverRow
                  key={item.symbol}
                  symbol={item.symbol}
                  name={item.name}
                  price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                  sentence={justReportedSentence(item)}
                />
              ))}
            </DiscoverRows>
          </section>
        ) : null}

        {/* ── Worth a look: the discover suggestion score, not Ivy's rule (hidden when every name duplicates Reporting soon) */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError && suggestionsAddValue ? (
          <section className="border-t border-border py-10">
            <SectionKicker index={nextIndex()} label="Suggestion score" />
            <h2 className="font-display text-xl font-bold text-foreground">Worth a look</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Ranked by a simple score: earnings soon, a recent reaction, realized volatility. Not Ivy&apos;s rule; her picks are on the ledger.</p>

            {suggestions && suggestions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No standout setups right now.
              </p>
            ) : (
              <DiscoverRows>
                {suggestions?.map((item) => (
                  <DiscoverRow
                    key={item.symbol}
                    symbol={item.symbol}
                    name={item.name}
                    price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                    sentence={suggestionSentence(item)}
                  />
                ))}
              </DiscoverRows>
            )}
          </section>
        ) : null}

        {/* ── 05 · Unusually active (hidden when empty) ── */}
        {!fetchError && loading ? (
          <SectionSkeleton />
        ) : !fetchError && unusuallyActive && unusuallyActive.length > 0 ? (
          <section className="border-t border-border py-10">
            <SectionKicker index={nextIndex()} label="The tape" />
            <h2 className="font-display text-xl font-bold text-foreground">Unusually active</h2>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Volatility high vs. their own norm</p>

            <DiscoverRows>
              {unusuallyActive.map((item) => (
                <DiscoverRow
                  key={item.symbol}
                  symbol={item.symbol}
                  name={item.name}
                  price={quotes.get(item.symbol)?.price != null ? fmtPrice(quotes.get(item.symbol)!.price) : undefined}
                  sentence={unusuallyActiveSentence(item)}
                />
              ))}
            </DiscoverRows>
          </section>
        ) : null}
      </div>
    </main>
  );
}
