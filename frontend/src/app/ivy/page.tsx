"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SectionKicker } from "@/components/SectionKicker";
import { api, type HealthStatus, type SystemStatus } from "@/lib/api";

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

function fmtRvDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const today = new Date();
  if (
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  )
    return "Today";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-border/60 py-2.5">
      <span className="font-mono text-xs uppercase text-muted-foreground">{label}</span>
      <span className="font-mono text-lg text-foreground">{value}</span>
    </div>
  );
}

export default function MeetIvyPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    Promise.all([api.system.health(), api.system.status()])
      .then(([h, s]) => {
        setHealth(h);
        setStatus(s);
      })
      .catch(() => setError(true));
  }, []);

  const loading = !health && !status && !error;

  // Build stat rows — only include non-null values
  const rows: { label: string; value: string }[] = [];
  if (!loading && !error) {
    if (health?.refresh_in_progress) {
      rows.push({ label: "Data refreshed", value: "Now" });
    } else if (health?.last_refreshed_at) {
      rows.push({ label: "Data refreshed", value: timeAgo(health.last_refreshed_at) });
    }
    if (status?.total_tickers != null) {
      rows.push({ label: "Tickers tracked", value: status.total_tickers.toLocaleString() });
    }
    if (status?.total_reactions != null) {
      rows.push({ label: "Reactions scanned", value: status.total_reactions.toLocaleString() });
    }
    if (health?.rv_latest_date) {
      rows.push({ label: "RV snapshot", value: fmtRvDate(health.rv_latest_date) });
    }
  }

  return (
    <div className="max-w-4xl pb-14">
      {/* ── 01 · Who she is ────────────────────────────────────── */}
      <section className="border-t border-border py-12">
        <SectionKicker index="01" label="Who she is" />
        <div className="grid grid-cols-1 md:grid-cols-[1.2fr_1fr] gap-12 items-start">
          <div>
            <h2 className="font-display text-3xl sm:text-4xl font-bold text-foreground leading-tight text-balance">
              The analyst inside Alert Interface
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed mt-4 max-w-prose">
              Ivy reads earnings history, live options data, and analyst moves for
              every ticker she tracks. She synthesizes the numbers into a direction,
              picks a strategy, and shows her reasoning on every call.
            </p>
          </div>

          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
              </span>
              <span className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
                Right now
              </span>
            </div>

            {loading && (
              <div className="space-y-3">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="flex justify-between border-b border-border/60 py-2.5">
                    <div className="h-3 w-28 animate-pulse rounded bg-muted" />
                    <div className="h-5 w-14 animate-pulse rounded bg-muted" />
                  </div>
                ))}
              </div>
            )}

            {!loading && !error && rows.length > 0 && (
              <div>
                {rows.map((r) => (
                  <StatRow key={r.label} label={r.label} value={r.value} />
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── 02 · How she decides ───────────────────────────────── */}
      <section className="border-t border-border py-12">
        <SectionKicker index="02" label="How she decides" />
        <div className="grid grid-cols-1 md:grid-cols-[1.2fr_1fr] gap-12">
          <div>
            <h2 className="font-display text-xl font-bold text-foreground">
              Grounded in data she can verify
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed mt-3 max-w-prose">
              Every pick gets a thesis, an entry mark, and a permanent score against
              the market. She weighs earnings surprise rates, historical move
              magnitudes, and the options-implied expected move before committing to a
              direction.
            </p>
          </div>
        </div>
      </section>

      {/* ── 03 · What she won't do ─────────────────────────────── */}
      <section className="border-t border-border py-12">
        <SectionKicker index="03" label="What she won&apos;t do" />
        <div className="grid grid-cols-1 md:grid-cols-[1.2fr_1fr] gap-12">
          <div>
            <h2 className="font-display text-xl font-bold text-foreground">
              No pick without a clear signal
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed mt-3 max-w-prose">
              She won&apos;t force a direction when the data is mixed. One pick per
              symbol, no stacking. And she never quietly edits her record; every
              call stays on the ledger exactly as she made it.
            </p>
          </div>
        </div>
      </section>

      {/* ── 04 · CTA row ───────────────────────────────────────── */}
      <section className="border-t border-border py-12">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <h3 className="font-display text-xl font-bold text-foreground">
            See what Ivy&apos;s working on
          </h3>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/ivy/picks"
              className="bg-primary text-primary-foreground font-semibold rounded-xl px-5 py-2.5 text-sm hover:opacity-90 transition-opacity"
            >
              See her current picks →
            </Link>
            <Link
              href="/ivy/trades"
              className="border border-border text-foreground font-semibold rounded-xl px-5 py-2.5 text-sm hover:border-foreground/40 transition-colors"
            >
              Her full record →
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
