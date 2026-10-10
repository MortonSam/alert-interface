"use client";

import { datasetAgeLine, optionsDataPhrase } from "@/lib/freshness";
import { evidenceSummary, ledgerHeadline, ledgerLinkLabel, limitLines, refusalTile, ruleTiles, whoSheIsLine, type RuleTile } from "@/lib/ivyRule";
import { IVY_BACKTEST_ENCODING, backtestScale, ivyBacktestLegend } from "@/lib/encodings/ivyBacktest";
import EncodingLegend from "@/components/EncodingLegend";
import { useIvyRule } from "@/lib/useIvyRule";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type HealthStatus, type IvyActivity } from "@/lib/api";
import { IvyMark } from "@/components/IvyMark";

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
        <span className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
          Latest stored data
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

function Tile({ tile, refusal = false }: { tile: RuleTile; refusal?: boolean }) {
  return (
    <div className={`h-full rounded-lg p-4 sm:p-5 ${refusal ? "border border-primary/60 bg-primary/[0.06]" : "border border-border bg-card/40"}`}>
      <p className="font-display text-3xl sm:text-4xl font-bold leading-none tracking-tight text-foreground tabular-nums">{tile.figure}</p>
      <p className="text-xs text-muted-foreground mt-1.5">{tile.unit}</p>
      <p className="text-sm text-foreground/85 leading-snug mt-4">{tile.caption}</p>
    </div>
  );
}

/** Her rule: three conditions joined by "and", then the refusal check that follows them. */
function RuleTiles({ tiles, refusal }: { tiles: RuleTile[]; refusal: RuleTile }) {
  return (
    <div className="mt-6 grid gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] lg:items-stretch">
      {tiles.map((t, i) => (
        <div key={t.unit} className="contents">
          {i > 0 && <span aria-hidden="true" className="hidden lg:flex items-center justify-center text-xs text-muted-foreground">and</span>}
          <Tile tile={t} />
        </div>
      ))}
      <span aria-hidden="true" className="hidden lg:flex items-center justify-center text-xs font-semibold text-primary">then</span>
      <div>
        <p className="text-xs text-primary mb-1.5 lg:hidden">Then she checks the options</p>
        <Tile tile={refusal} refusal />
      </div>
    </div>
  );
}

function EvidenceChart({ folds }: { folds: { label: string; setups: number; hitRate: number | null; baseRate: number | null }[] }) {
  const rates = folds.flatMap((f) => [f.hitRate, f.baseRate]).filter((r): r is number => r != null);
  if (!rates.length) return null;
  const { min, max } = backtestScale(rates);
  const x = (r: number) => `${((r * 100 - min) / (max - min)) * 100}%`;
  const ticks = Array.from({ length: max - min + 1 }, (_, i) => min + i).filter((t) => t % 2 === 0);
  const dot = (key: keyof typeof IVY_BACKTEST_ENCODING, r: number) => {
    const e = IVY_BACKTEST_ENCODING[key];
    return (
      <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 h-3 w-3 rounded-full"
            style={{ left: x(r), backgroundColor: e.filled ? e.color : "hsl(var(--background))", border: `2px solid ${e.color}` }}
            title={`${e.label}: ${(r * 100).toFixed(1)}%`} />
    );
  };
  return (
    <div>
      <div className="space-y-3">
        {folds.map((f) => (
          <div key={f.label} className="grid grid-cols-[4.5rem_1fr] items-center gap-3">
            <span className="text-xs text-muted-foreground tabular-nums">{f.label}</span>
            <div className="relative h-5">
              <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
              {f.hitRate != null && f.baseRate != null && (
                <span className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-primary/40"
                      style={{ left: x(Math.min(f.hitRate, f.baseRate)), width: `${(Math.abs(f.hitRate - f.baseRate) * 100 / (max - min)) * 100}%` }} />
              )}
              {f.baseRate != null && dot("base", f.baseRate)}
              {f.hitRate != null && dot("setups", f.hitRate)}
            </div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-[4.5rem_1fr] gap-3 mt-2">
        <span />
        <div className="relative h-4 text-[10px] text-muted-foreground tabular-nums">
          {ticks.map((t) => <span key={t} className="absolute -translate-x-1/2" style={{ left: `${((t - min) / (max - min)) * 100}%` }}>{t}%</span>)}
        </div>
      </div>
      <EncodingLegend items={ivyBacktestLegend()} className="mt-3" />
    </div>
  );
}

export default function MeetIvyPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [activity, setActivity] = useState<IvyActivity | null>(null);
  const [error, setError] = useState(false);
  const ivy = useIvyRule();

  useEffect(() => {
    Promise.allSettled([api.system.health(), api.theses.ivyActivity()])
      .then(([hResult, aResult]) => {
        if (hResult.status === "fulfilled") setHealth(hResult.value);
        if (aResult.status === "fulfilled") setActivity(aResult.value);
        if (hResult.status === "rejected") setError(true);
      });
  }, []);

  const loading = !health && !activity && !error;

  const railRows: { label: string; value: string }[] = [];
  if (!loading && !error) {
    if (health?.refresh_in_progress) {
      railRows.push({ label: "Data refreshed", value: "Now" });
    } else if (datasetAgeLine(health?.datasets, ["chains", "reactions"], timeAgo)) {
      railRows.push({ label: "Data refreshed", value: datasetAgeLine(health?.datasets, ["chains", "reactions"], timeAgo) as string });
    }
    if (health?.rv_latest_date) {
      railRows.push({ label: "RV snapshot", value: fmtRvDate(health.rv_latest_date) });
    }
    if (activity?.run_date) {
      const datePart = fmtRvDate(activity.run_date);
      railRows.push({ label: "Last evaluation", value: `${datePart} · ${activity.evaluated} names` });
    }
  }

  const evidence = ivy ? evidenceSummary(ivy.rule, ivy.backtest) : null;

  return (
    <div className="pb-14">
      {/* Who she is, with the latest stored data beside it from 1024px up and under it below */}
      <div className="lg:grid lg:grid-cols-[1fr_300px] lg:gap-x-12 pt-4 sm:pt-6">
        <section className="pb-10">
          <h2 className="font-display text-4xl sm:text-5xl font-bold text-foreground leading-tight text-balance flex items-center gap-4">
            <IvyMark size={48} className="shrink-0" />
            <span>The analyst inside Alert Interface</span>
          </h2>
          <p className="text-lg text-foreground/80 leading-relaxed mt-4 max-w-prose">
            {ivy ? whoSheIsLine(ivy.rule) : "She reads the tape overnight and makes a call only when her one setup appears."}
          </p>
          <p className="text-base text-muted-foreground leading-relaxed mt-3 max-w-prose">
            She reads each company&apos;s earnings history and {optionsDataPhrase(health?.options_data_date, health?.cadence)},
            applies one rule the backtest supports, and refuses when the options are too expensive for the edge.
          </p>
          {activity?.run_date && (
            <Link href="/ivy/desk" className="inline-block text-sm text-muted-foreground hover:text-foreground transition-colors mt-4">
              See last night&apos;s worksheet →
            </Link>
          )}
        </section>
        <aside className="pb-10 lg:pt-1">
          <StatsBlock loading={loading} error={error} rows={railRows} />
        </aside>
      </div>

      {/* Her rule */}
      {ivy && (
        <section className="border-t border-border pt-10 pb-14">
          <h2 className="font-display text-2xl font-bold text-foreground">{ledgerHeadline(ivy.rule)}</h2>
          <p className="text-sm text-muted-foreground mt-2 max-w-prose">She picks only when all three hold, then checks what the options are pricing.</p>
          <RuleTiles tiles={ruleTiles(ivy.rule)} refusal={refusalTile(ivy.rule)} />
        </section>
      )}

      {/* The evidence */}
      {evidence && (
        <section className="border-t border-border pt-10 pb-14 lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-x-12">
          <div>
            <h2 className="font-display text-2xl font-bold text-foreground">The evidence</h2>
            <p className="text-sm text-muted-foreground mt-2">Tested against {evidence.years}.</p>
            <div className="mt-6 flex items-end gap-6 sm:gap-8">
              <div>
                <p className="font-display text-5xl font-bold leading-none tabular-nums text-primary">{evidence.hitRate}%</p>
                <p className="text-xs text-muted-foreground mt-2 max-w-[16ch]">of her {evidence.setups} setups were higher five days later</p>
              </div>
              <div>
                <p className="font-display text-3xl font-bold leading-none tabular-nums text-foreground/70">{evidence.baseRate}%</p>
                <p className="text-xs text-muted-foreground mt-2 max-w-[16ch]">for all earnings reports in those years</p>
              </div>
            </div>
            <p className="text-sm text-foreground/80 leading-relaxed mt-6 max-w-prose">{evidence.honest}</p>
          </div>
          <div className="mt-8 lg:mt-1">
            <p className="text-sm text-muted-foreground mb-4">Higher five days later, by year</p>
            <EvidenceChart folds={evidence.folds} />
          </div>
        </section>
      )}

      {/* Her limits */}
      {ivy && (
        <section className="border-t border-border pt-10 pb-14">
          <h2 className="font-display text-2xl font-bold text-foreground">Her limits</h2>
          <ul className="mt-5 grid gap-x-10 sm:grid-cols-2">
            {limitLines(ivy.rule).map((line) => (
              <li key={line} className="flex gap-3 border-b border-border/60 py-3 text-sm text-foreground/85 leading-snug">
                <span aria-hidden="true" className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* To her desk */}
      <section className="border-t border-border pt-10 pb-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 sm:gap-6">
          <h3 className="font-display text-xl font-bold text-foreground">
            See what Ivy&apos;s working on
          </h3>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/ivy/desk"
              className="bg-primary text-primary-foreground font-semibold rounded-xl px-5 py-2.5 text-sm hover:opacity-90 transition-opacity whitespace-nowrap"
            >
              See what&apos;s on her desk →
            </Link>
            <Link
              href="/ivy/trades"
              className="border border-border text-foreground font-semibold rounded-xl px-5 py-2.5 text-sm hover:border-foreground/40 transition-colors whitespace-nowrap"
            >
              {ivy ? ledgerLinkLabel(ivy.rule) : "Her record \u2192"}
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
