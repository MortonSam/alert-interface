"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  api,
  type ReportingSoonItem,
  type JustReportedItem,
  type SuggestionItem,
  type BatchQuote,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

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

// ── Section header ──────────────────────────────────────────────────────────

function SectionHeader({
  icon,
  iconBg,
  title,
  descriptor,
  total,
  limit,
}: {
  icon: React.ReactNode;
  iconBg: string;
  title: string;
  descriptor: string;
  total: number | null;
  limit: number;
}) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div
        className={`flex items-center justify-center h-8 w-8 rounded-lg ${iconBg}`}
      >
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <h2 className="font-display text-lg font-bold text-foreground">
          {title}
        </h2>
        <p className="text-xs text-muted-foreground">{descriptor}</p>
      </div>
      {total != null && total > limit && (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          see all {total} &rarr;
        </span>
      )}
    </div>
  );
}

// ── Skeletons ────────────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 animate-pulse">
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
    <div>
      <div className="flex items-center gap-3 mb-4">
        <div className="h-8 w-8 rounded-lg bg-muted animate-pulse" />
        <div>
          <div className="h-5 w-32 bg-muted rounded mb-1 animate-pulse" />
          <div className="h-3 w-48 bg-muted rounded animate-pulse" />
        </div>
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
  const [quotes, setQuotes] = useState<Map<string, BatchQuote>>(new Map());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.discover.reportingSoon(7, LIMIT),
      api.discover.justReported(5, LIMIT),
      api.discover.suggestions(5),
    ]).then(([rs, jr, sg]) => {
      setReportingSoon(rs);
      setJustReported(jr);
      setSuggestions(sg.items);
      setLoading(false);

      // Batch-fetch quotes for all displayed symbols
      const allSymbols = [
        ...rs.items.map((i) => i.symbol),
        ...jr.items.map((i) => i.symbol),
        ...sg.items.map((i) => i.symbol),
      ];
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
    });
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
          <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
            Discover
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            What&apos;s worth researching across your universe right now.
          </p>
        </div>

        <div className="space-y-12">
          {/* ── Reporting soon ─────────────────────────────── */}
          {loading ? (
            <SectionSkeleton />
          ) : (
            <section>
              <SectionHeader
                icon={
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-amber-500"
                  >
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                }
                iconBg="bg-amber-500/10"
                title="Reporting soon"
                descriptor="Earnings in the next 7 days"
                total={reportingSoon?.total ?? null}
                limit={LIMIT}
              />

              {reportingSoon && reportingSoon.items.length === 0 ? (
                <div className="rounded-xl border border-border bg-card px-6 py-8 text-center">
                  <p className="text-sm text-muted-foreground">
                    Nothing reporting in the next 7 days.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {reportingSoon?.items.map((item) => {
                    const days = daysUntil(item.earnings_date);
                    const q = quotes.get(item.symbol);
                    const tagLabel =
                      days <= 0
                        ? "EPS today"
                        : days === 1
                          ? "EPS in 1d"
                          : `EPS in ${days}d`;
                    return (
                      <Link
                        key={item.symbol}
                        href={`/tickers/${item.symbol}`}
                        className="rounded-xl border border-border bg-card p-4 hover:border-amber-500/40 transition-colors group"
                      >
                        <div className="flex items-start justify-between mb-1">
                          <span className="font-display text-base font-bold text-foreground group-hover:text-amber-500 transition-colors">
                            {item.symbol}
                          </span>
                          {q?.price != null && (
                            <span className="font-mono text-xs text-muted-foreground">
                              {fmtPrice(q.price)}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate mb-3">
                          {item.name ?? "\u2014"}
                        </p>
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 px-2.5 py-1 text-[11px] font-semibold tracking-wide">
                          <span className="text-[8px]">{"\u25CF"}</span>
                          {tagLabel}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {/* ── Just reported ─────────────────────────────── */}
          {loading ? (
            <SectionSkeleton />
          ) : (
            <section>
              <SectionHeader
                icon={
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-cool"
                  >
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                  </svg>
                }
                iconBg="bg-cool/10"
                title="Just reported"
                descriptor="Notable earnings reaction in the last 5 days"
                total={justReported?.total ?? null}
                limit={LIMIT}
              />

              {justReported && justReported.items.length === 0 ? (
                <div className="rounded-xl border border-border bg-card px-6 py-8 text-center">
                  <p className="text-sm text-muted-foreground">
                    No notable earnings reactions in the last 5 days.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {justReported?.items.map((item) => {
                    const q = quotes.get(item.symbol);
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
                        ? "text-emerald-500"
                        : move != null && move < 0
                          ? "text-red-500"
                          : "text-muted-foreground";
                    const moveStr =
                      move != null
                        ? `${move > 0 ? "+" : ""}${move.toFixed(1)}%`
                        : "";

                    return (
                      <Link
                        key={item.symbol}
                        href={`/tickers/${item.symbol}`}
                        className="rounded-xl border border-border bg-card p-4 hover:border-cool/40 transition-colors group"
                      >
                        <div className="flex items-start justify-between mb-1">
                          <span className="font-display text-base font-bold text-foreground group-hover:text-cool transition-colors">
                            {item.symbol}
                          </span>
                          {q?.price != null && (
                            <span className="font-mono text-xs text-muted-foreground">
                              {fmtPrice(q.price)}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate mb-3">
                          {item.name ?? "\u2014"}
                        </p>
                        <span className="inline-flex items-center gap-2 rounded-full bg-cool/10 text-cool px-2.5 py-1 text-[11px] font-semibold tracking-wide">
                          <span className="text-[8px]">{"\u25CF"}</span>
                          {outcomeLabel}
                          {moveStr && (
                            <span className={moveColor}>{moveStr}</span>
                          )}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {/* ── AI suggestions ─────────────────────────────── */}
          {loading ? (
            <SectionSkeleton />
          ) : (
            <section>
              <SectionHeader
                icon={
                  <span className="text-primary text-sm leading-none">
                    {"\u2726"}
                  </span>
                }
                iconBg="bg-primary/10"
                title="AI suggestions"
                descriptor="Stocks worth a look right now"
                total={null}
                limit={LIMIT}
              />

              {suggestions && suggestions.length === 0 ? (
                <div className="rounded-xl border border-border bg-card px-6 py-8 text-center">
                  <p className="text-sm text-muted-foreground">
                    No standout setups right now.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {suggestions?.map((item) => {
                    const q = quotes.get(item.symbol);
                    return (
                      <Link
                        key={item.symbol}
                        href={`/tickers/${item.symbol}`}
                        className="rounded-xl border border-border bg-card p-4 hover:border-primary/40 transition-colors group"
                      >
                        <div className="flex items-start justify-between mb-1">
                          <span className="font-display text-base font-bold text-foreground group-hover:text-primary transition-colors">
                            {item.symbol}
                          </span>
                          {q?.price != null && (
                            <span className="font-mono text-xs text-muted-foreground">
                              {fmtPrice(q.price)}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate">
                          {item.name ?? "\u2014"}
                        </p>
                      </Link>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {/* ── Unusually active (placeholder) ────────────── */}
          <section className="opacity-50">
            <SectionHeader
              icon={
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="text-violet"
                >
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
              }
              iconBg="bg-violet/10"
              title="Unusually active"
              descriptor="Stocks with elevated realized volatility vs. their own history"
              total={null}
              limit={LIMIT}
            />
            <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-8 text-center">
              <p className="text-sm text-muted-foreground">
                Coming soon &mdash; requires precomputing RV rank across the
                universe.
              </p>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
