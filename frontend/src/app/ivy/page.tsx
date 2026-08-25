"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type HealthStatus, type IvyActivity, type SystemStatus } from "@/lib/api";

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

function StatsBlock({
  loading,
  error,
  rows,
}: {
  loading: boolean;
  error: boolean;
  rows: { label: string; value: string }[];
}) {
  return (
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
          {[1, 2, 3].map((i) => (
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
  );
}

function LeanDot({ direction }: { direction: string }) {
  return (
    <span
      className={
        "w-2 h-2 rounded-full inline-block " +
        (direction === "bullish"
          ? "bg-green-500"
          : direction === "bearish"
            ? "bg-red-500"
            : "bg-zinc-400")
      }
    />
  );
}

function GutterNumber({ n }: { n: string }) {
  return (
    <span className="font-mono text-xs text-muted-foreground">{n}</span>
  );
}

function SectionLabel({ label }: { label: string }) {
  return (
    <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">
      {label}
    </p>
  );
}

export default function MeetIvyPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [activity, setActivity] = useState<IvyActivity | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    Promise.allSettled([api.system.health(), api.system.status(), api.theses.ivyActivity()])
      .then(([hResult, sResult, aResult]) => {
        if (hResult.status === "fulfilled") setHealth(hResult.value);
        if (sResult.status === "fulfilled") setStatus(sResult.value);
        if (aResult.status === "fulfilled") setActivity(aResult.value);
        if (hResult.status === "rejected" && sResult.status === "rejected") setError(true);
      });
  }, []);

  const loading = !health && !status && !error;

  // Rail rows (reduced set)
  const railRows: { label: string; value: string }[] = [];
  if (!loading && !error) {
    if (health?.refresh_in_progress) {
      railRows.push({ label: "Data refreshed", value: "Now" });
    } else if (health?.last_refreshed_at) {
      railRows.push({ label: "Data refreshed", value: timeAgo(health.last_refreshed_at) });
    }
    if (health?.rv_latest_date) {
      railRows.push({ label: "RV snapshot", value: fmtRvDate(health.rv_latest_date) });
    }
    if (activity?.run_date) {
      const datePart = fmtRvDate(activity.run_date);
      railRows.push({ label: "Last evaluation", value: `${datePart} · ${activity.evaluated} names` });
    }
  }

  // Hero proof numerals
  const proofNumerals: { value: string; label: string }[] = [];
  if (!loading && !error) {
    if (status?.total_tickers != null) {
      proofNumerals.push({ value: status.total_tickers.toLocaleString(), label: "Tickers tracked" });
    }
    if (status?.total_reactions != null) {
      proofNumerals.push({ value: status.total_reactions.toLocaleString(), label: "Reactions scanned" });
    }
    if (activity?.evaluated != null && activity.evaluated > 0) {
      proofNumerals.push({ value: activity.evaluated.toLocaleString(), label: "Evaluated last night" });
    }
  }

  const refusal = activity?.sample_refusal ?? null;

  return (
    <div className="pb-14">
      {/* Mobile/tablet: stats block first */}
      <div className="lg:hidden mb-8 border-t border-border pt-8">
        <StatsBlock loading={loading} error={error} rows={railRows} />
      </div>

      {/* 3-column grid (lg+) / single column (below) */}
      <div className="lg:grid lg:grid-cols-[96px_1fr_320px] lg:gap-x-10">

        {/* Right rail (sticky, desktop only) */}
        <aside className="hidden lg:block lg:col-start-3 lg:row-start-1 lg:row-span-5">
          <div className="sticky top-[5rem] border-t border-border pt-10">
            <StatsBlock loading={loading} error={error} rows={railRows} />
          </div>
        </aside>

        {/* 01 Who she is */}
        <div className="hidden lg:block border-t border-border pt-10">
          <GutterNumber n="01" />
        </div>
        <section className="border-t border-border pt-10 pb-20">
          <SectionLabel label="Who she is" />
          <h2 className="font-display text-5xl font-bold text-foreground leading-tight text-balance">
            The analyst inside Alert Interface
          </h2>
          <p className="text-lg text-muted-foreground leading-relaxed mt-2 max-w-prose">
            She reads the tape overnight, makes a call only when the evidence agrees, and keeps score in public.
          </p>
          <p className="text-base text-muted-foreground leading-relaxed mt-4 max-w-prose">
            Ivy reads earnings history, live options data, and analyst moves for
            every ticker she tracks. She synthesizes the numbers into a direction,
            picks a strategy, and shows her reasoning on every call.
          </p>

          {/* Proof row */}
          {proofNumerals.length > 0 && (
            <div className="border-t border-b border-border mt-8 py-6 flex gap-10 flex-wrap">
              {proofNumerals.map((n) => (
                <div key={n.label}>
                  <span className="font-display text-5xl tabular-nums text-foreground">{n.value}</span>
                  <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground mt-1">{n.label}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 02 How she decides */}
        <div className="hidden lg:block border-t border-border pt-10">
          <GutterNumber n="02" />
        </div>
        <section className="border-t border-border pt-10 pb-20">
          <SectionLabel label="How she decides" />
          <h2 className="font-display text-2xl font-bold text-foreground">
            Grounded in data she can verify
          </h2>
          <p className="text-base text-muted-foreground leading-relaxed mt-3 max-w-prose">
            Every pick gets a thesis, an entry mark, and a permanent score against
            the market. She weighs earnings surprise rates, historical move
            magnitudes, and the options-implied expected move before committing to a
            direction.
          </p>

          {/* Lean legend */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mt-6">
            <div className="flex items-center gap-1.5">
              <LeanDot direction="bullish" />
              <span className="text-xs text-muted-foreground">Earnings</span>
            </div>
            <div className="flex items-center gap-1.5">
              <LeanDot direction="bearish" />
              <span className="text-xs text-muted-foreground">Analyst</span>
            </div>
            <div className="flex items-center gap-1.5">
              <LeanDot direction="neutral" />
              <span className="text-xs text-muted-foreground">Momentum</span>
            </div>
            <span className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
              Two must agree. None may oppose.
            </span>
          </div>
        </section>

        {/* 03 What she won't do */}
        <div className="hidden lg:block border-t border-border pt-10">
          <GutterNumber n="03" />
        </div>
        <section className="border-t border-border pt-10 pb-20">
          <SectionLabel label="What she won&apos;t do" />
          <h2 className="font-display text-2xl font-bold text-foreground">
            No pick without a clear signal
          </h2>
          <p className="text-base text-muted-foreground leading-relaxed mt-3 max-w-prose">
            She won&apos;t force a direction when the data is mixed. One pick per
            symbol, no stacking. And she never quietly edits her record; every
            call stays on the ledger exactly as she made it.
          </p>

          {/* Sample refusal receipt */}
          {refusal && (
            <p className="text-sm text-muted-foreground mt-6">
              Last night she passed on {refusal.symbol}.{" "}
              {refusal.leans.map((l, i) => (
                <span key={l.signal} className="inline-flex items-center gap-1">
                  {i > 0 && ", "}
                  <LeanDot direction={l.direction} />
                  <span className="capitalize">{l.signal}</span>
                  {" "}{l.direction}
                </span>
              ))}.
            </p>
          )}
        </section>

        {/* 04 CTA row */}
        <div className="hidden lg:block border-t border-border pt-10" />
        <section className="border-t border-border pt-10 pb-4">
          <div className="flex items-center justify-between gap-6">
            <h3 className="font-display text-xl font-bold text-foreground whitespace-nowrap">
              See what Ivy&apos;s working on
            </h3>
            <div className="flex gap-3">
              <Link
                href="/ivy/picks"
                className="bg-primary text-primary-foreground font-semibold rounded-xl px-5 py-2.5 text-sm hover:opacity-90 transition-opacity whitespace-nowrap"
              >
                See her current picks →
              </Link>
              <Link
                href="/ivy/trades"
                className="border border-border text-foreground font-semibold rounded-xl px-5 py-2.5 text-sm hover:border-foreground/40 transition-colors whitespace-nowrap"
              >
                Her full record →
              </Link>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
