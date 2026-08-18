"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
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

function StatTile({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-lg font-semibold text-foreground">{value}</span>
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
        {label}
      </span>
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

  // Build stat tiles — only include non-null values
  const tiles: { value: string; label: string }[] = [];
  if (!loading && !error) {
    if (health?.refresh_in_progress) {
      tiles.push({ value: "Now", label: "Refreshing" });
    } else if (health?.last_refreshed_at) {
      tiles.push({ value: timeAgo(health.last_refreshed_at), label: "Data refreshed" });
    }
    if (status?.total_tickers != null) {
      tiles.push({ value: String(status.total_tickers), label: "Tickers tracked" });
    }
    if (status?.total_reactions != null) {
      tiles.push({ value: status.total_reactions.toLocaleString(), label: "Reactions scanned" });
    }
    if (health?.rv_latest_date) {
      tiles.push({ value: health.rv_latest_date, label: "RV snapshot" });
    }
  }

  return (
    <div className="space-y-12 pb-14">
      {/* ── Intro row ──────────────────────────────────────────── */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
        {/* Left — Who she is */}
        <div>
          <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-2">
            Who she is
          </p>
          <h2 className="font-display text-4xl sm:text-5xl font-bold text-foreground leading-tight">
            The analyst inside Alert Interface
          </h2>
          <p className="text-sm text-muted-foreground leading-relaxed mt-4">
            Ivy reads earnings history, live options data, and analyst moves for
            every ticker she tracks. She synthesizes the numbers into a direction,
            picks a strategy, and shows her reasoning on every call.
          </p>
        </div>

        {/* Right — Live status card */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 mb-4">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
            </span>
            <span className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
              Right now
            </span>
          </div>

          {loading && (
            <div className="grid grid-cols-2 gap-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-1.5">
                  <div className="h-5 w-16 animate-pulse rounded bg-muted" />
                  <div className="h-3 w-24 animate-pulse rounded bg-muted" />
                </div>
              ))}
            </div>
          )}

          {!loading && !error && tiles.length > 0 && (
            <div className="grid grid-cols-2 gap-4">
              {tiles.map((t) => (
                <StatTile key={t.label} value={t.value} label={t.label} />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ── Philosophy cards ───────────────────────────────────── */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* How she decides */}
        <div className="rounded-xl border border-border bg-card/60 p-5 border-l-[3px] border-l-cool">
          <p className="font-mono text-[10px] uppercase tracking-[.16em] text-cool mb-2">
            How she decides
          </p>
          <h3 className="font-display text-[15px] font-bold text-foreground mb-2">
            Grounded in data she can verify
          </h3>
          <p className="text-[13px] text-foreground/75 leading-[1.65]">
            Every pick gets a thesis, an entry mark, and a permanent score against
            the market. She weighs earnings surprise rates, historical move
            magnitudes, and the options-implied expected move before committing to a
            direction.
          </p>
        </div>

        {/* What she won't do */}
        <div className="rounded-xl border border-border bg-card/60 p-5 border-l-[3px] border-l-primary">
          <p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary mb-2">
            What she won&apos;t do
          </p>
          <h3 className="font-display text-[15px] font-bold text-foreground mb-2">
            No pick without a clear signal
          </h3>
          <p className="text-[13px] text-foreground/75 leading-[1.65]">
            She won&apos;t force a direction when the data is mixed. One pick per
            symbol, no stacking. And she never quietly edits her record; every
            call stays on the ledger exactly as she made it.
          </p>
        </div>
      </section>

      {/* ── CTA band ───────────────────────────────────────────── */}
      <section className="rounded-xl border border-border bg-card/60 px-6 py-8 text-center">
        <h3 className="font-display text-lg font-bold text-foreground">
          See what Ivy&apos;s working on
        </h3>
        <div className="flex flex-wrap gap-3 justify-center mt-5">
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
      </section>
    </div>
  );
}
