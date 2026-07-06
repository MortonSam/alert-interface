"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, notFound } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from "recharts";
import { api, type Ticker, type TickerQuote, type TickerChart, type EarningsMarker, type Event, type EventType, type EarningsOutcome, type HistoricalReaction, type ReactionSummary, type ResearchNote, type VerificationClaim, type VerificationResult, type OptionsRead, type RealizedVol, type ExpectedMove, type OptionsChain, type StrategyData, type StrikeData, type NewsResponse } from "@/lib/api";
import { cn, rvRankShort } from "@/lib/utils";
import Callout from "@/components/Callout";
import StructuredNoteView from "@/components/StructuredNoteView";
import Tip from "@/components/Tip";
import {
  BS_R, BS_IV_DEFAULT, MS_PER_YEAR,
  type Leg, dateMs, erfApprox, normCDF,
  blackScholes, multiLegPayoffPS, multiLegPayoffBSPS,
} from "@/lib/black-scholes";

// ── Date / number helpers ─────────────────────────────────────────────────────

const TODAY = (() => {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
})();
const CURRENT_YEAR = TODAY.getFullYear();

function formatMarketCap(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

function formatEventDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (y !== CURRENT_YEAR) opts.year = "numeric";
  return date.toLocaleDateString("en-US", opts);
}

function daysFromToday(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  return Math.round((new Date(y, m - 1, d).getTime() - TODAY.getTime()) / 86_400_000);
}

function formatPrice(v: string | null): string {
  if (v == null) return "—";
  return `$${parseFloat(v).toFixed(2)}`;
}

function formatVolume(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v.toLocaleString();
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins  = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days  = Math.floor(diff / 86_400_000);
  if (mins < 1)   return "just now";
  if (mins < 60)  return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function timeAgoUnix(unixSeconds: number): string {
  return timeAgo(new Date(unixSeconds * 1000).toISOString());
}

// ── Catalyst section helpers ──────────────────────────────────────────────────

const EVENT_STYLES: Record<EventType, { label: string; cls: string }> = {
  earnings:       { label: "Earnings",       cls: "bg-cool/10 text-cool" },
  macro:          { label: "Macro",          cls: "bg-violet/10 text-violet" },
  fda:            { label: "FDA",            cls: "bg-success/10 text-success" },
  ex_dividend:    { label: "Ex-Div",         cls: "bg-secondary text-muted-foreground" },
  product_launch: { label: "Launch",         cls: "bg-primary/10 text-primary" },
  other:          { label: "Other",          cls: "bg-muted text-muted-foreground" },
};

function EventTypeBadge({ type }: { type: EventType }) {
  const { label, cls } = EVENT_STYLES[type] ?? EVENT_STYLES.other;
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

const OUTCOME_STYLES: Record<EarningsOutcome, { label: string; cls: string }> = {
  beat:    { label: "Beat",    cls: "bg-success/10 text-success" },
  miss:    { label: "Miss",    cls: "bg-destructive/10 text-destructive" },
  meet:    { label: "Meet",    cls: "bg-secondary text-muted-foreground" },
  unknown: { label: "—",       cls: "bg-muted text-muted-foreground" },
};

function OutcomeBadge({ outcome }: { outcome: EarningsOutcome }) {
  const { label, cls } = OUTCOME_STYLES[outcome] ?? OUTCOME_STYLES.unknown;
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function DaysBadge({ days }: { days: number }) {
  const label = days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
  const cls =
    days <= 7   ? "bg-primary/10 text-primary"
    : days <= 30 ? "bg-amber-500/10 text-amber-500"
    : "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium tabular-nums ${cls}`}>
      {label}
    </span>
  );
}

function CatalystRow({ event }: { event: Event }) {
  const days = daysFromToday(event.event_date);
  return (
    <div className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
      <div className="w-14 shrink-0 pt-0.5 text-sm tabular-nums text-muted-foreground">
        {formatEventDate(event.event_date)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{event.title}</span>
          <EventTypeBadge type={event.event_type} />
          <DaysBadge days={days} />
        </div>
        {event.description && (
          <p className="mt-0.5 text-xs text-muted-foreground line-clamp-1">{event.description}</p>
        )}
      </div>
    </div>
  );
}

// ── Earnings insights panel ───────────────────────────────────────────────────

function EarningsInsightsPanel({ s }: { s: ReactionSummary }) {
  const dropRate = s.beat_but_dropped_rate_pct;
  const pricingNote =
    dropRate == null ? null
    : dropRate >= 50 ? "beats appear largely priced in"
    : dropRate >= 25 ? "beats partially priced in"
    : "beats tend to drive the stock higher";

  const sectorVsOwn =
    s.sector_avg_abs_1d != null && s.avg_abs_1d != null
      ? s.avg_abs_1d < s.sector_avg_abs_1d * 0.85 ? "smaller than"
      : s.avg_abs_1d > s.sector_avg_abs_1d * 1.15 ? "larger than"
      : "similar to"
      : null;

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-3 mb-3">
      {/* Beat rate + beat-but-dropped headline */}
      <div>
        <p className="text-sm font-semibold">
          Beat EPS in {s.beat_count} of {s.total_quarters} quarter{s.total_quarters !== 1 ? "s" : ""}{" "}
          ({s.beat_rate_pct.toFixed(0)}%)
        </p>
        {dropRate != null && s.beat_count > 0 && (
          <p
            className={cn(
              "text-sm mt-0.5",
              dropRate >= 50
                ? "text-amber-700 dark:text-amber-400"
                : "text-muted-foreground",
            )}
          >
            Stock fell next day in {s.beat_but_dropped_count} of {s.beat_count} beats
            {" "}({dropRate.toFixed(0)}%){pricingNote ? ` — ${pricingNote}` : ""}
          </p>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-2">
        {(
          [
            ["Avg T+1 on beats", s.avg_1d_on_beat],
            ["Avg T+1 on misses", s.avg_1d_on_miss],
          ] as [string, number | null][]
        ).map(([label, val]) => (
          <div key={label}>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">{label}</p>
            <p
              className={cn(
                "text-sm font-semibold tabular-nums",
                val == null ? "text-muted-foreground"
                : val > 0 ? "text-green-700 dark:text-green-400"
                : "text-red-600 dark:text-red-400",
              )}
            >
              {val == null ? "—" : `${val > 0 ? "+" : ""}${val.toFixed(2)}%`}
            </p>
          </div>
        ))}

        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Avg abs move</p>
          <p className="text-sm font-semibold tabular-nums text-foreground">
            {s.avg_abs_1d != null ? `±${s.avg_abs_1d.toFixed(2)}%` : "—"}
          </p>
        </div>

        {s.sector_avg_abs_1d != null && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">
              {s.sector ?? "Sector"} avg move
            </p>
            <p className="text-sm font-semibold tabular-nums text-muted-foreground">
              ±{s.sector_avg_abs_1d.toFixed(2)}%
            </p>
          </div>
        )}
      </div>

      {/* Sector comparison sentence */}
      {sectorVsOwn != null && s.avg_abs_1d != null && s.sector_avg_abs_1d != null && (
        <p className="text-xs text-muted-foreground">
          Typical earnings move (±{s.avg_abs_1d.toFixed(2)}%) is{" "}
          <span className="font-medium">{sectorVsOwn}</span> the{" "}
          {s.sector ?? "sector"} peer average (±{s.sector_avg_abs_1d.toFixed(2)}%){" "}
          across {s.sector_peer_count} peers
        </p>
      )}
    </div>
  );
}

// ── Reactions table ───────────────────────────────────────────────────────────

type ReactionSortKey = "event_date" | "pct_change_1d" | "pct_change_3d" | "pct_change_5d";
type OutcomeFilter = "all" | "beat" | "miss" | "meet";

// ── Stats helpers ─────────────────────────────────────────────────────────────

interface MoveStats { avg: number; median: number; max: number; min: number }

function computeStats(values: number[]): MoveStats | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const avg = values.reduce((s, v) => s + v, 0) / values.length;
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
  return { avg, median, max: sorted[sorted.length - 1], min: sorted[0] };
}

function pctValues(rows: HistoricalReaction[], key: "pct_change_1d" | "pct_change_3d" | "pct_change_5d"): number[] {
  return rows.flatMap((r) => (r[key] != null ? [parseFloat(r[key]!)] : []));
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PctCell({ value }: { value: string | null }) {
  if (value == null) {
    return <td className="px-3 py-2.5 text-right text-sm text-muted-foreground tabular-nums">—</td>;
  }
  const n = parseFloat(value);
  return (
    <td
      className={cn(
        "px-3 py-2.5 text-right text-sm font-medium tabular-nums",
        n > 0 && "text-green-700 dark:text-green-400",
        n < 0 && "text-red-600 dark:text-red-400",
        n === 0 && "text-muted-foreground",
      )}
    >
      <span
        className={cn(
          "inline-block rounded px-1",
          n > 0 && "bg-green-50 dark:bg-green-900/20",
          n < 0 && "bg-red-50 dark:bg-red-900/20",
        )}
      >
        {n > 0 ? "+" : ""}
        {n.toFixed(2)}%
      </span>
    </td>
  );
}

function StatNum({ value }: { value: number }) {
  return (
    <span
      className={cn(
        "tabular-nums font-medium text-sm",
        value > 0 && "text-green-700 dark:text-green-400",
        value < 0 && "text-red-600 dark:text-red-400",
        value === 0 && "text-muted-foreground",
      )}
    >
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

function SortTh({
  label,
  col,
  sort,
  onSort,
  align = "right",
}: {
  label: string;
  col: ReactionSortKey;
  sort: { key: ReactionSortKey; dir: "asc" | "desc" };
  onSort: (col: ReactionSortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === col;
  return (
    <th
      className={cn(
        "px-3 py-2.5 text-xs font-medium uppercase tracking-wide cursor-pointer select-none whitespace-nowrap",
        "hover:text-foreground transition-colors",
        active ? "text-foreground" : "text-muted-foreground",
        align === "right" ? "text-right" : "text-left",
      )}
      onClick={() => onSort(col)}
    >
      {label}
      {active && <span className="ml-1 opacity-60">{sort.dir === "asc" ? "↑" : "↓"}</span>}
    </th>
  );
}

// ── Distribution panel ────────────────────────────────────────────────────────

function upRate(rows: HistoricalReaction[], key: "pct_change_1d" | "pct_change_3d" | "pct_change_5d"): string {
  const valid = rows.filter((r) => r[key] != null);
  if (valid.length === 0) return "—";
  const up = valid.filter((r) => parseFloat(r[key]!) > 0).length;
  const pct = Math.round((up / valid.length) * 100);
  return `${up} of ${valid.length} (${pct}%)`;
}

function DistributionPanel({ rows, filter }: { rows: HistoricalReaction[]; filter: OutcomeFilter }) {
  const n = rows.length;

  const s1d = computeStats(pctValues(rows, "pct_change_1d"));
  const s3d = computeStats(pctValues(rows, "pct_change_3d"));
  const s5d = computeStats(pctValues(rows, "pct_change_5d"));

  let filterLabel: string;
  if (filter === "all")  filterLabel = `${n} earning${n === 1 ? "" : "s"}`;
  else if (filter === "beat") filterLabel = `${n} beat${n === 1 ? "" : "s"}`;
  else if (filter === "miss") filterLabel = `${n} miss${n === 1 ? "" : "es"}`;
  else filterLabel = `${n} meet${n === 1 ? "" : "s"}`;

  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <div className="flex items-baseline gap-2 mb-0.5">
        <span className="text-sm font-semibold">Distribution</span>
        <span className="text-xs text-muted-foreground">Based on {filterLabel}</span>
      </div>
      <p className="text-xs text-muted-foreground italic mb-3">
        Stats below show stock price moves, not EPS surprise magnitude.
      </p>

      {n < 3 ? (
        <p className="text-xs text-muted-foreground italic">
          Limited sample size — interpret with caution.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className="text-left font-medium text-muted-foreground pb-2 pr-4 w-8" />
                  <th className="text-right font-medium text-muted-foreground pb-2 pr-4">Avg</th>
                  <th className="text-right font-medium text-muted-foreground pb-2 pr-4">Median</th>
                  <th className="text-right font-medium text-muted-foreground pb-2 pr-4">Max</th>
                  <th className="text-right font-medium text-muted-foreground pb-2">Min</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {(
                  [
                    ["1d", s1d],
                    ["3d", s3d],
                    ["5d", s5d],
                  ] as [string, MoveStats | null][]
                ).map(([label, s]) => (
                  <tr key={label}>
                    <td className="py-1.5 pr-4 text-muted-foreground font-medium">{label}</td>
                    {s ? (
                      <>
                        <td className="py-1.5 pr-4 text-right"><StatNum value={s.avg} /></td>
                        <td className="py-1.5 pr-4 text-right"><StatNum value={s.median} /></td>
                        <td className="py-1.5 pr-4 text-right"><StatNum value={s.max} /></td>
                        <td className="py-1.5 text-right"><StatNum value={s.min} /></td>
                      </>
                    ) : (
                      <td colSpan={4} className="py-1.5 text-right text-muted-foreground">—</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Stock up:{" "}
            <span className="font-medium">{upRate(rows, "pct_change_1d")}</span> on day 1 /{" "}
            <span className="font-medium">{upRate(rows, "pct_change_3d")}</span> on day 3 /{" "}
            <span className="font-medium">{upRate(rows, "pct_change_5d")}</span> on day 5
          </p>
        </>
      )}
    </div>
  );
}

// ── Main table ────────────────────────────────────────────────────────────────

function ReactionsTable({ reactions }: { reactions: HistoricalReaction[] }) {
  const [sort, setSort] = useState<{ key: ReactionSortKey; dir: "asc" | "desc" }>({
    key: "event_date",
    dir: "desc",
  });
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");

  function handleSort(col: ReactionSortKey) {
    setSort((prev) =>
      prev.key === col
        ? { key: col, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key: col, dir: "desc" },
    );
  }

  const counts = useMemo(
    () => ({
      all:  reactions.length,
      beat: reactions.filter((r) => r.outcome === "beat").length,
      miss: reactions.filter((r) => r.outcome === "miss").length,
      meet: reactions.filter((r) => r.outcome === "meet").length,
    }),
    [reactions],
  );

  const filtered = useMemo(
    () => (outcomeFilter === "all" ? reactions : reactions.filter((r) => r.outcome === outcomeFilter)),
    [reactions, outcomeFilter],
  );

  const sorted = useMemo(() => {
    const nullLast = sort.dir === "asc" ? Infinity : -Infinity;
    return [...filtered].sort((a, b) => {
      const mul = sort.dir === "asc" ? 1 : -1;
      if (sort.key === "event_date") {
        return mul * a.event_date.localeCompare(b.event_date);
      }
      const av = a[sort.key] != null ? parseFloat(a[sort.key]!) : nullLast;
      const bv = b[sort.key] != null ? parseFloat(b[sort.key]!) : nullLast;
      return mul * (av - bv);
    });
  }, [filtered, sort]);

  function pluralOutcome(key: OutcomeFilter, n: number): string {
    if (key === "all")  return `All (${n})`;
    if (key === "beat") return n === 1 ? `Beat (1)` : `Beats (${n})`;
    if (key === "miss") return n === 1 ? `Miss (1)` : `Misses (${n})`;
    if (key === "meet") return n === 1 ? `Meet (1)` : `Meets (${n})`;
    return `${n}`;
  }

  const PILLS: { key: OutcomeFilter; label: string }[] = [
    { key: "all",  label: pluralOutcome("all",  counts.all) },
    { key: "beat", label: pluralOutcome("beat", counts.beat) },
    { key: "miss", label: pluralOutcome("miss", counts.miss) },
    { key: "meet", label: pluralOutcome("meet", counts.meet) },
  ];

  return (
    <div className="space-y-3">
      {/* Filter pills */}
      <div className="flex flex-wrap gap-2">
        {PILLS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setOutcomeFilter(key)}
            className={cn(
              "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium transition-colors",
              outcomeFilter === key
                ? key === "beat" ? "bg-success/10 text-success"
                  : key === "miss" ? "bg-destructive/10 text-destructive"
                  : key === "meet" ? "bg-secondary text-secondary-foreground"
                  : "bg-foreground text-background"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Distribution */}
      <DistributionPanel rows={filtered} filter={outcomeFilter} />

      {/* Table */}
      <div className="rounded-lg border bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <SortTh label="Date"    col="event_date"    sort={sort} onSort={handleSort} align="left" />
                <th className="px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Event
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    Outcome
                    <span
                      title="Beat/miss/meet refers to EPS surprise vs. analyst estimate. Stock direction is shown separately by the arrow next to the badge and the 1d/3d/5d columns. Companies can beat EPS and still see the stock fall, or miss and still rally."
                      className="cursor-help opacity-60 hover:opacity-100 transition-opacity"
                    >
                      ⓘ
                    </span>
                  </span>
                </th>
                <th className="px-3 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Open (T)
                </th>
                <SortTh label="1d %"  col="pct_change_1d" sort={sort} onSort={handleSort} />
                <SortTh label="3d %"  col="pct_change_3d" sort={sort} onSort={handleSort} />
                <SortTh label="5d %"  col="pct_change_5d" sort={sort} onSort={handleSort} />
                <th className="px-3 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Volume
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sorted.map((r) => (
                <tr key={r.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-3 py-2.5 text-sm tabular-nums text-muted-foreground whitespace-nowrap">
                    {formatEventDate(r.event_date)}
                  </td>
                  <td className="px-3 py-2.5">
                    <EventTypeBadge type={r.event_type} />
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="inline-flex items-center gap-1.5 flex-wrap">
                      <OutcomeBadge outcome={r.outcome} />
                      {r.eps_surprise_pct != null && (
                        <span
                          className={cn(
                            "text-xs font-medium tabular-nums",
                            r.eps_surprise_pct > 0
                              ? "text-green-600 dark:text-green-400"
                              : "text-red-500 dark:text-red-400",
                          )}
                        >
                          {r.eps_surprise_pct > 0 ? "+" : ""}
                          {r.eps_surprise_pct.toFixed(1)}%
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right text-sm tabular-nums">
                    {formatPrice(r.open_after)}
                  </td>
                  <PctCell value={r.pct_change_1d} />
                  <PctCell value={r.pct_change_3d} />
                  <PctCell value={r.pct_change_5d} />
                  <td className="px-3 py-2.5 text-right text-sm tabular-nums text-muted-foreground">
                    {formatVolume(r.volume_after)}
                  </td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    No rows match the selected filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="px-3 py-2 text-xs text-muted-foreground border-t bg-muted/20">
          Moves measured from event-day open price. Days are calendar days, rolling forward to next
          trading day on weekends/holidays.
        </p>
      </div>
    </div>
  );
}

// ── Verification panel ────────────────────────────────────────────────────────

const CLAIM_STYLES: Record<VerificationClaim["status"], { dot: string; badge: string; label: string }> = {
  supported:    { dot: "bg-success",      badge: "bg-success/10 text-success",           label: "Supported" },
  unsupported:  { dot: "bg-amber-500",    badge: "bg-amber-500/10 text-amber-500",      label: "Unsupported" },
  contradicted: { dot: "bg-destructive",  badge: "bg-destructive/10 text-destructive",  label: "Contradicted" },
};

function VerificationPanel({
  verification,
  verifiedAt,
  model,
  open,
  onToggle,
}: {
  verification: VerificationResult;
  verifiedAt: string | null;
  model: string | null;
  open: boolean;
  onToggle: () => void;
}) {
  const { supported, unsupported, contradicted } = verification.summary;
  const total = supported + unsupported + contradicted;

  return (
    <div className="border-t">
      {/* Summary bar / toggle */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-6 py-3 text-xs hover:bg-muted/30 transition-colors"
      >
        <span className="flex items-center gap-3 font-medium">
          <span className="text-green-600 dark:text-green-400">✓ {supported} supported</span>
          <span className="text-amber-600 dark:text-amber-400">⚠ {unsupported} unsupported</span>
          {contradicted > 0
            ? <span className="text-red-600 dark:text-red-400">✗ {contradicted} contradicted</span>
            : <span className="text-muted-foreground">✗ 0 contradicted</span>
          }
          <span className="text-muted-foreground font-normal">
            · verified {verifiedAt ? timeAgo(verifiedAt) : "—"}{model ? ` · ${model}` : ""}
          </span>
        </span>
        <span className="text-muted-foreground">{open ? "▲" : "▼"} {total} claims</span>
      </button>

      {/* Expandable claims list */}
      {open && (
        <div className="px-6 pb-5 space-y-2">
          {verification.claims.map((c, i) => {
            const style = CLAIM_STYLES[c.status];
            return (
              <div key={i} className="flex gap-3 text-sm">
                <div className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${style.dot}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-2 flex-wrap">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium shrink-0 ${style.badge}`}>
                      {style.label}
                    </span>
                    <span className="text-foreground/90">{c.claim}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">{c.evidence}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Price chart ───────────────────────────────────────────────────────────────

const CHART_PERIODS = ["1d", "7d", "1mo", "3mo", "6mo", "1y", "5y"] as const;
type ChartPeriod = (typeof CHART_PERIODS)[number];

const PERIOD_LABELS: Record<ChartPeriod, string> = {
  "1d": "1D", "7d": "1W", "1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1Y", "5y": "5Y",
};

const PERIOD_WINDOW_LABEL: Record<ChartPeriod, string> = {
  "1d": "today",
  "7d": "past 1w",
  "1mo": "past month",
  "3mo": "past 3 months",
  "6mo": "past 6 months",
  "1y": "past year",
  "5y": "past 5 years",
};

/** Format tooltip date: intraday ISO → "May 28, 10:30 AM ET"; daily → raw date string. */
function formatTooltipDate(date: string, period: ChartPeriod): string {
  if (date.length > 10) {
    const d = new Date(date);
    if (period === "1d") {
      return d.toLocaleTimeString("en-US", {
        hour: "numeric", minute: "2-digit", hour12: true,
        timeZone: "America/New_York",
      });
    }
    // 7D: show "May 28, 10:30 AM"
    return d.toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit", hour12: true,
      timeZone: "America/New_York",
    });
  }
  return date;
}

const OUTCOME_DOT_COLOR: Record<EarningsMarker["outcome"], string> = {
  beat: "hsl(var(--success))",
  miss: "hsl(var(--destructive))",
  meet: "hsl(var(--muted-foreground))",
  unknown: "hsl(var(--muted-foreground))",
};

function formatYTick(v: number): string {
  return `$${v.toFixed(0)}`;
}

function PriceChartTooltip({
  active, payload, markerMap, period,
}: {
  active?: boolean;
  payload?: Array<{ payload: { date: string; close: number; epochMs: number } }>;
  markerMap: Map<string, EarningsMarker>;
  period: ChartPeriod;
}) {
  if (!active || !payload?.length) return null;
  const { date, close } = payload[0].payload;
  const marker = markerMap.get(date);
  return (
    <div className="rounded-lg border bg-card shadow-md px-3 py-2 text-xs min-w-[140px]">
      <p className="font-medium text-foreground mb-1">{formatTooltipDate(date, period)}</p>
      <p className="tabular-nums">${close.toFixed(2)}</p>
      {marker && (
        <div className="mt-1.5 pt-1.5 border-t space-y-0.5">
          <p className={cn(
            "font-semibold",
            marker.outcome === "beat" && "text-green-600",
            marker.outcome === "miss" && "text-red-600",
            (marker.outcome === "meet" || marker.outcome === "unknown") && "text-muted-foreground",
          )}>
            Earnings · {marker.outcome.charAt(0).toUpperCase() + marker.outcome.slice(1)}
          </p>
          {(marker.eps_estimate != null || marker.eps_actual != null) && (
            <p className="text-muted-foreground">
              EPS {marker.eps_actual != null ? `$${marker.eps_actual.toFixed(2)}` : "—"}
              {marker.eps_estimate != null && ` vs $${marker.eps_estimate.toFixed(2)} est`}
            </p>
          )}
          {marker.pct_change_1d != null && (
            <p className={marker.pct_change_1d >= 0 ? "text-green-600" : "text-red-600"}>
              1d {marker.pct_change_1d >= 0 ? "+" : ""}{marker.pct_change_1d.toFixed(2)}%
              {marker.pct_change_3d != null && ` · 3d ${marker.pct_change_3d >= 0 ? "+" : ""}${marker.pct_change_3d.toFixed(2)}%`}
              {marker.pct_change_5d != null && ` · 5d ${marker.pct_change_5d >= 0 ? "+" : ""}${marker.pct_change_5d.toFixed(2)}%`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function PriceChart({
  symbol,
  period,
  onPeriodChange,
  onChartLoad,
}: {
  symbol: string;
  period: ChartPeriod;
  onPeriodChange: (p: ChartPeriod) => void;
  onChartLoad: (startPrice: number | null) => void;
}) {
  const [chartData, setChartData] = useState<TickerChart | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    onChartLoad(null); // clear header change while loading new range
    api.tickers.chart(symbol, period).then((d) => {
      setChartData(d);
      onChartLoad(d.start_price);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [symbol, period, onChartLoad]);

  // Intraday periods use index-based x-axis to eliminate overnight/weekend gaps.
  const isIntraday = period === "1d" || period === "7d";

  // Build chart data. Each point gets: date (raw), epochMs (for tooltip/lookup), close, idx.
  const { lineData, markerMap } = useMemo(() => {
    const empty = {
      lineData: [] as Array<{ date: string; epochMs: number; close: number; idx: number }>,
      markerMap: new Map<string, EarningsMarker>(),
    };
    if (!chartData) return empty;
    const mm = new Map<string, EarningsMarker>(
      chartData.earnings_markers.map((m) => [m.date, m])
    );
    const ld = chartData.history.map((p, i) => ({
      date: p.date,
      epochMs: p.date.length > 10
        ? new Date(p.date).getTime()
        : new Date(p.date + "T12:00:00Z").getTime(),
      close: p.close,
      idx: i,
    }));
    return { lineData: ld, markerMap: mm };
  }, [chartData]);

  // x-axis ticks
  const xTicks = useMemo(() => {
    if (lineData.length < 2) return [];
    if (period === "1d") {
      // Evenly-spaced indices (6 ticks) for single-day intraday
      const n = Math.min(6, lineData.length);
      return Array.from({ length: n }, (_, i) =>
        lineData[Math.floor((i / (n - 1)) * (lineData.length - 1))].idx
      );
    }
    if (period === "7d") {
      // One tick at the first bar of each trading day
      const seen = new Set<string>();
      const ticks: number[] = [];
      for (const bar of lineData) {
        const dayKey = new Date(bar.epochMs).toLocaleDateString("en-CA", {
          timeZone: "America/New_York", // "YYYY-MM-DD" format via en-CA locale
        });
        if (!seen.has(dayKey)) {
          seen.add(dayKey);
          ticks.push(bar.idx);
        }
      }
      return ticks;
    }
    // Daily periods: epochMs-based, ~6 evenly spaced
    const n = Math.min(6, lineData.length);
    return Array.from({ length: n }, (_, i) =>
      lineData[Math.floor((i / (n - 1)) * (lineData.length - 1))].epochMs
    );
  }, [lineData, period]);

  // y-axis: tight domain framing actual price range, padded 5%
  // Also include start_price (prev close reference line) so it stays in view on 1D
  const yDomain = useMemo((): [number, number] | ["auto", "auto"] => {
    if (!lineData.length) return ["auto", "auto"];
    const vals = lineData.map((d) => d.close);
    if (chartData?.start_price != null) vals.push(chartData.start_price);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const pad = (hi - lo) * 0.05;
    return [lo - pad, hi + pad];
  }, [lineData, chartData?.start_price]);

  // x-axis tick formatter
  // For intraday (1D/7D): val is a bar index — look up the real timestamp from lineData.
  // For daily: val is epochMs directly.
  const formatXTick = (val: number) => {
    if (period === "1d") {
      const bar = lineData[val];
      if (!bar) return "";
      return new Date(bar.epochMs).toLocaleTimeString("en-US", {
        hour: "numeric", minute: "2-digit", hour12: true,
        timeZone: "America/New_York",
      });
    }
    if (period === "7d") {
      const bar = lineData[val];
      if (!bar) return "";
      return new Date(bar.epochMs).toLocaleDateString("en-US", {
        month: "short", day: "numeric",
        timeZone: "America/New_York",
      });
    }
    if (period === "1mo" || period === "3mo") {
      return new Date(val).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    }
    return new Date(val).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  };

  // Earnings marker reference lines (vertical)
  const markerDates = useMemo(() => {
    return chartData?.earnings_markers.map((m) => ({
      ...m,
      epochMs: new Date(m.date + "T12:00:00Z").getTime(),
    })) ?? [];
  }, [chartData]);

  if (loading) {
    return (
      <div className="h-52 rounded-lg border bg-card animate-pulse mt-6" />
    );
  }

  if (!chartData || lineData.length === 0) return null;

  // Use start_price as the reference for color (green if current > start)
  const refPrice = chartData.start_price ?? lineData[0].close;
  const isUp = lineData[lineData.length - 1].close >= refPrice;
  const lineColor = isUp ? "hsl(var(--success))" : "hsl(var(--destructive))";

  return (
    <div className="mt-6 rounded-lg border bg-card px-4 pt-4 pb-2">
      {/* Period selector */}
      <div className="flex gap-1 mb-3">
        {CHART_PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => onPeriodChange(p)}
            className={cn(
              "px-2.5 py-0.5 rounded text-xs font-medium transition-colors",
              period === p
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground hover:bg-muted",
            )}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground self-center pr-1">
          {markerDates.length > 0 && `${markerDates.length} earnings marker${markerDates.length !== 1 ? "s" : ""}`}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={lineData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis
            dataKey={isIntraday ? "idx" : "epochMs"}
            type="number"
            domain={isIntraday ? [0, lineData.length - 1] : ["dataMin", "dataMax"]}
            scale={isIntraday ? "linear" : "time"}
            ticks={xTicks}
            tickFormatter={formatXTick}
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={yDomain}
            tickFormatter={formatYTick}
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            axisLine={false}
            tickLine={false}
            width={50}
          />
          <Tooltip
            content={<PriceChartTooltip markerMap={markerMap} period={period} />}
            cursor={{ stroke: "hsl(var(--muted-foreground))", strokeWidth: 1, strokeDasharray: "4 2" }}
          />

          {/* Previous-close reference line for 1D intraday view */}
          {period === "1d" && chartData.start_price != null && (
            <ReferenceLine
              y={chartData.start_price}
              stroke="hsl(var(--muted-foreground))"
              strokeWidth={1}
              strokeDasharray="4 2"
              strokeOpacity={0.45}
            />
          )}

          {/* Vertical dashed lines at each earnings date — daily ranges only (epochMs x-axis) */}
          {!isIntraday && markerDates.map((m) => (
            <ReferenceLine
              key={m.date}
              x={m.epochMs}
              stroke={OUTCOME_DOT_COLOR[m.outcome]}
              strokeWidth={1}
              strokeDasharray="3 3"
              strokeOpacity={0.6}
            />
          ))}

          <Line
            dataKey="close"
            dot={(props: { cx?: number; cy?: number; payload?: { date: string } }) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null || !payload) return <g key="empty" />;
              const marker = markerMap.get(payload.date);
              if (!marker) return <g key={payload.date} />;
              return (
                <circle
                  key={payload.date}
                  cx={cx}
                  cy={cy}
                  r={5}
                  fill={OUTCOME_DOT_COLOR[marker.outcome]}
                  stroke="white"
                  strokeWidth={1.5}
                />
              );
            }}
            activeDot={{ r: 4, fill: lineColor }}
            stroke={lineColor}
            strokeWidth={1.5}
            type="linear"
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* Legend */}
      {markerDates.length > 0 && (
        <div className="flex gap-4 mt-1 px-1 pb-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-success" /> Beat
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-destructive" /> Miss
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-muted-foreground" /> Meet / Unknown
          </span>
        </div>
      )}
    </div>
  );
}

// ── Stat strip ────────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium">{value ?? "—"}</span>
    </div>
  );
}

// ── Options / IV helpers ──────────────────────────────────────────────────────

function fmtPctDecimal(v: number | null, digits = 1): string {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

const TIPS = {
  iv:           "Implied Volatility — the market's forecast of how much this stock will move, stated as an annualized %. Higher IV = bigger expected swings = pricier options.",
  atm:          "At-The-Money — the strike price closest to where the stock is currently trading. The expected move is anchored here.",
  straddle:     "A straddle is buying both an ATM call and an ATM put. Its total cost equals the market's best guess at the stock's move in either direction.",
  impliedRange: "The price range the market thinks the stock will stay within by expiration, derived from options pricing. About 68% of outcomes are expected to fall inside this band.",
  impliedMove:  "Derived from the ATM straddle price divided by the stock price. It's what options traders collectively expect the stock to move — in either direction — by expiration.",
  bid:          "The highest price a buyer is currently willing to pay for this option contract.",
  ask:          "The lowest price a seller will accept. The fair value is usually near the midpoint between bid and ask.",
  openInterest: "The total number of open option contracts at this strike that haven't been closed or exercised. High open interest means more market participation.",
  strike:       "The fixed price at which the option lets you buy (call) or sell (put) the stock, regardless of where the stock actually trades.",
} as const;

// ── ExpectedMoveCard ──────────────────────────────────────────────────────────

function ExpectedMoveCard({ em, onSelectExpiration }: { em: ExpectedMove; onSelectExpiration?: (exp: string) => void }) {
  const emPct = em.expected_move_pct;
  const emDol = em.expected_move_dollars;
  const stats = em.historical_stats;
  const daysPast = em.days_expiration_past_earnings;

  // "isolated" = expiration falls within 3 days of earnings, so straddle ≈ earnings-day premium
  const isIsolated = daysPast != null && daysPast <= 3;
  // windows are mismatched when expiration is far past earnings (implied = multi-week vol, historical = 1-day move)
  const windowsMismatched = em.earnings_date != null && daysPast != null && daysPast > 3;

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-4">
      {/* Headline */}
      <div>
        <div className="text-2xl font-bold tabular-nums">
          {emPct != null ? `±${fmtPctDecimal(emPct)}` : "—"}
          {emDol != null && (
            <span className="text-lg font-semibold text-muted-foreground ml-2">
              (${emDol.toFixed(2)})
            </span>
          )}
        </div>

        {/* Primary subtitle: always shows what the number actually covers */}
        <p className="text-sm text-muted-foreground mt-0.5">
          {isIsolated
            ? <>Earnings-day implied move — expiration{" "}
                {em.expiration_used && (
                  <button
                    className="underline underline-offset-2 hover:text-foreground transition-colors"
                    onClick={() => onSelectExpiration?.(em.expiration_used!)}
                  >
                    {em.expiration_used}
                  </button>
                )}{" "}
                is {daysPast === 0 ? "same day as" : `${daysPast}d after`} the {em.earnings_date} earnings
              </>
            : em.earnings_date
              ? <>Implied move by{" "}
                  {em.expiration_used && (
                    <button
                      className="underline underline-offset-2 hover:text-foreground transition-colors"
                      onClick={() => onSelectExpiration?.(em.expiration_used!)}
                    >
                      {em.expiration_used}
                    </button>
                  )}
                </>
              : <>Market implied move by{" "}
                  {em.expiration_used && (
                    <button
                      className="underline underline-offset-2 hover:text-foreground transition-colors"
                      onClick={() => onSelectExpiration?.(em.expiration_used!)}
                    >
                      {em.expiration_used}
                    </button>
                  )}
                </>
          }
        </p>

        {/* Window-mismatch warning banner */}
        {windowsMismatched && (
          <Callout severity="info" compact className="mt-1.5">
            This covers the full period to expiration — <strong>{daysPast} days past the {em.earnings_date} earnings</strong>.
            It reflects total vol over that window, not just the earnings event.
          </Callout>
        )}
      </div>

      {/* Implied range */}
      {em.implied_range_low != null && em.implied_range_high != null && (
        <div className="flex items-center gap-3 text-sm">
          <Tip text={TIPS.impliedRange}>
            <span className="text-muted-foreground underline decoration-dotted underline-offset-2">
              Implied range
            </span>
          </Tip>
          <span className="font-semibold tabular-nums">
            ${em.implied_range_low.toFixed(2)}
            <span className="text-muted-foreground mx-2">–</span>
            ${em.implied_range_high.toFixed(2)}
          </span>
        </div>
      )}

      {/* ATM detail */}
      {(em.atm_strike != null || em.straddle_price != null) && (
        <p className="text-xs text-muted-foreground flex items-center gap-1 flex-wrap">
          {em.atm_strike != null && (
            <Tip text={TIPS.atm}>
              <span className="underline decoration-dotted underline-offset-2">
                ATM strike ${em.atm_strike}
              </span>
            </Tip>
          )}
          {em.atm_strike != null && em.straddle_price != null && <span>·</span>}
          {em.straddle_price != null && (
            <Tip text={TIPS.straddle}>
              <span className="underline decoration-dotted underline-offset-2">
                straddle ${em.straddle_price.toFixed(2)}
              </span>
            </Tip>
          )}
        </p>
      )}

      {/* Historical 1-day earnings moves */}
      {stats && stats.sample_size >= 2 && (
        <div className="rounded-md border bg-muted/30 px-4 py-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Past earnings-day 1d moves (n={stats.sample_size})
          </p>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <p className="text-xs text-muted-foreground">Avg</p>
              <p className="text-sm font-semibold tabular-nums">±{fmtPctDecimal(stats.avg_abs_move_pct)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Max</p>
              <p className="text-sm font-semibold tabular-nums">±{fmtPctDecimal(stats.max_abs_move_pct)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Min</p>
              <p className="text-sm font-semibold tabular-nums">±{fmtPctDecimal(stats.min_abs_move_pct)}</p>
            </div>
          </div>

          {/* Only show direct comparison when windows match */}
          {isIsolated ? (
            <p className="text-xs text-muted-foreground">
              {stats.above_expected} of {stats.sample_size} past earnings exceeded this implied move ·{" "}
              historical avg ±{fmtPctDecimal(stats.avg_abs_move_pct)}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground italic">
              Direct comparison unavailable — the implied ±{fmtPctDecimal(emPct)} covers{" "}
              {daysPast != null ? `${daysPast} days past earnings` : "multiple weeks"}, while these
              figures measure the single earnings day only.
            </p>
          )}
        </div>
      )}

      {/* Data quality note — only shown when not already covered by the window-mismatch banner */}
      {em.data_quality_note && !windowsMismatched && (
        <p className="text-xs text-muted-foreground italic">{em.data_quality_note}</p>
      )}
    </div>
  );
}

// ── OptionsEducation ──────────────────────────────────────────────────────────

function OptionsEducation({
  em,
  chain,
  symbol,
}: {
  em: ExpectedMove;
  chain: OptionsChain;
  symbol: string;
}) {
  const [open, setOpen] = useState(false);

  const atmCall   = chain.calls.find((c) => c.is_atm);
  const atmPut    = chain.puts.find((p)  => p.is_atm);
  const strike    = em.atm_strike;
  const price     = em.current_price;
  const emPct     = em.expected_move_pct;
  const exp       = em.expiration_used;

  const callMid = atmCall
    ? atmCall.bid != null && atmCall.ask != null
      ? (atmCall.bid + atmCall.ask) / 2
      : atmCall.last_price
    : null;
  const putMid = atmPut
    ? atmPut.bid != null && atmPut.ask != null
      ? (atmPut.bid + atmPut.ask) / 2
      : atmPut.last_price
    : null;

  const callBreakeven = strike != null && callMid != null ? strike + callMid : null;
  const putBreakeven  = strike != null && putMid  != null ? strike - putMid  : null;
  const callIV        = atmCall?.implied_volatility;

  return (
    <div className="mt-6 rounded-lg border bg-card overflow-visible">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-medium hover:bg-muted/30 transition-colors text-left"
        aria-expanded={open}
      >
        <span>How options work — applied to {symbol}</span>
        <span className="text-muted-foreground text-xs shrink-0 ml-4">{open ? "▲ Collapse" : "▼ Expand"}</span>
      </button>

      {open && (
        <div className="border-t divide-y divide-border/60">

          {/* 1 — Calls & Puts */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">Calls & Puts</h3>
            <p className="text-muted-foreground">
              A <strong className="text-foreground">call option</strong> gives you the right to{" "}
              <em>buy</em> {symbol} at a fixed price (the <em>strike</em>) by the expiration date —
              no matter how high the stock goes.
              {strike != null && callMid != null && (
                <> The ${strike} call currently costs about{" "}
                  <strong className="text-foreground">${callMid.toFixed(2)}</strong> per share.
                  You profit if {symbol} climbs above{" "}
                  <strong className="text-foreground">
                    ${callBreakeven?.toFixed(2)}
                  </strong>{" "}
                  by {exp} — that's the strike plus the option's cost (your breakeven).
                </>
              )}
            </p>
            <p className="text-muted-foreground">
              A <strong className="text-foreground">put option</strong> is the mirror image — the
              right to <em>sell</em> at the strike, useful when you expect the stock to fall.
              {strike != null && putMid != null && (
                <> The ${strike} put costs about{" "}
                  <strong className="text-foreground">${putMid.toFixed(2)}</strong>.
                  It profits if {symbol} drops below{" "}
                  <strong className="text-foreground">
                    ${putBreakeven?.toFixed(2)}
                  </strong>{" "}
                  by {exp}.
                </>
              )}
            </p>
            <p className="text-muted-foreground">
              Options expire worthless if the stock never reaches the breakeven. You can also sell
              them before expiry — if the stock moves your way, the option gains value even before
              expiration.
            </p>
          </section>

          {/* 2 — Expected Move */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">The Expected Move</h3>
            <p className="text-muted-foreground">
              The "expected move" comes from adding the ATM call and put prices together — a
              position called a <em>straddle</em>.
              {em.straddle_price != null && strike != null && (
                <> The ${strike} straddle costs{" "}
                  <strong className="text-foreground">${em.straddle_price.toFixed(2)}</strong>.
                  That's the market's implied range of motion in either direction.
                </>
              )}
            </p>
            {emPct != null && em.implied_range_low != null && em.implied_range_high != null && (
              <p className="text-muted-foreground">
                Dividing by the stock price gives{" "}
                <strong className="text-foreground">±{(emPct * 100).toFixed(1)}%</strong>, which
                puts the implied range at{" "}
                <strong className="text-foreground">
                  ${em.implied_range_low.toFixed(2)}–${em.implied_range_high.toFixed(2)}
                </strong>{" "}
                by {exp}. Any option struck <em>outside</em> that range is a bet that {symbol} moves
                more than the market currently expects.
              </p>
            )}
            {em.days_expiration_past_earnings != null && em.earnings_date && (
              <p className="text-muted-foreground text-xs italic">
                Note: the expiration is {em.days_expiration_past_earnings} days past the{" "}
                {em.earnings_date} earnings, so this range reflects the full period to expiration,
                not just the single earnings day.
              </p>
            )}
          </section>

          {/* 3 — Implied Volatility */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">Implied Volatility (IV)</h3>
            <p className="text-muted-foreground">
              IV is the market's forecast of how much a stock will move, expressed as an annualized
              percentage. High IV = bigger expected swings = pricier options. Low IV = calmer
              expectations = cheaper options.
              {callIV != null && price != null && (
                <> {symbol}'s ATM call IV is currently{" "}
                  <strong className="text-foreground">{(callIV * 100).toFixed(1)}%</strong>{" "}
                  annualized.
                </>
              )}
            </p>
            {callIV != null && (
              <p className="text-muted-foreground">
                You can estimate the expected <em>daily</em> move by dividing by √252 (trading days
                per year): {(callIV * 100).toFixed(1)}% ÷ 15.9 ≈{" "}
                <strong className="text-foreground">
                  {((callIV / Math.sqrt(252)) * 100).toFixed(1)}% per day
                </strong>
                . Whether that's high or low <em>for {symbol} specifically</em> is called IV Rank — a
                future feature.
              </p>
            )}
          </section>

          {/* 4 — Reading the Chain */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">Reading the Chain</h3>
            <p className="text-muted-foreground">
              The options chain shows every available strike for a given expiration. Each row has a
              call on the left and a put on the right, with the strike price in the middle. The{" "}
              <strong className="text-foreground">ATM row</strong> (highlighted in blue) is where the
              expected move is anchored.
            </p>
            <p className="text-muted-foreground">
              <strong className="text-foreground">Bid/Ask:</strong> the prices market makers will
              buy/sell at — the fair value is usually the midpoint.{" "}
              <strong className="text-foreground">IV</strong> is color-coded: warmer (orange) means
              higher implied volatility, cooler (blue) means lower. Notice that put IV is often
              higher than call IV at the same strike — this is called <em>volatility skew</em>,
              reflecting the market's greater fear of sharp drops than sharp rallies.
            </p>
          </section>

        </div>
      )}
    </div>
  );
}

// ── Strategy Explainer ────────────────────────────────────────────────────────

type StrategyType = "long_call" | "long_put" | "covered_call" | "csp";
type MultiLegType = "bear_call_spread" | "short_strangle" | "iron_condor";
type Outlook = "bullish" | "bearish" | "neutral";

interface StrategyMeta {
  name: string;
  oneLiner: string;
  description: string;
  usesCall: boolean;
}

const STRATEGY_META: Record<StrategyType, StrategyMeta> = {
  long_call: {
    name: "Long Call",
    oneLiner: "Bullish — pay a premium for the right to buy shares at the strike.",
    description:
      "A long call profits when the stock rises above your breakeven by expiration. " +
      "Risk is capped at the premium paid — no matter how far the stock falls, that's " +
      "the most you can lose. Upside is theoretically unlimited as the stock moves higher.",
    usesCall: true,
  },
  long_put: {
    name: "Long Put",
    oneLiner: "Bearish — pay a premium for the right to sell shares at the strike.",
    description:
      "A long put profits when the stock falls below your breakeven. Risk is limited " +
      "to the premium paid. Maximum gain is the strike minus the premium (approached " +
      "as the stock nears zero). A defined-risk way to express a bearish view.",
    usesCall: false,
  },
  covered_call: {
    name: "Covered Call",
    oneLiner: "Mildly bullish or neutral — sell a call against 100 shares you already own.",
    description:
      "You own 100 shares and sell a call at the chosen strike, collecting the premium " +
      "immediately. If the stock stays below the strike at expiration you keep both the " +
      "shares and the premium, reducing your effective cost basis. If it rises above, " +
      "your shares get called away at the strike — capping your upside.",
    usesCall: true,
  },
  csp: {
    name: "Cash-Secured Put",
    oneLiner: "Neutral to bullish — sell a put with cash set aside to buy shares if assigned.",
    description:
      "You sell a put and hold enough cash to buy 100 shares if the stock falls to the " +
      "strike. If it stays above, you keep the premium — your maximum gain. If it falls " +
      "below, you effectively buy the stock at (strike − premium), often below today's price. " +
      "Generates income while expressing willingness to own the stock at a lower price.",
    usesCall: false,
  },
};

const OUTLOOK_STRATEGIES: Record<Outlook, (StrategyType | MultiLegType)[]> = {
  bullish: ["long_call", "covered_call", "csp"],
  bearish: ["long_put", "bear_call_spread"],
  neutral: ["short_strangle", "iron_condor"],
};

function payoffPS(
  strategy: StrategyType,
  K: number,
  premium: number,
  currentPrice: number,
  S: number,
): number {
  switch (strategy) {
    case "long_call":    return Math.max(0, S - K) - premium;
    case "long_put":     return Math.max(0, K - S) - premium;
    case "covered_call": return (S - currentPrice) + premium - Math.max(0, S - K);
    case "csp":          return premium - Math.max(0, K - S);
  }
}

interface StrategyStats {
  maxGain: number | null;  // null = unlimited
  maxLoss: number;
  breakevens: number[];
}

function strategyStats(
  strategy: StrategyType,
  K: number,
  premium: number,
  currentPrice: number,
): StrategyStats {
  switch (strategy) {
    case "long_call":
      return { maxGain: null, maxLoss: premium, breakevens: [K + premium] };
    case "long_put":
      return { maxGain: K - premium, maxLoss: premium, breakevens: [K - premium] };
    case "covered_call":
      return {
        maxGain: K - currentPrice + premium,
        maxLoss: currentPrice - premium,
        breakevens: [currentPrice - premium],
      };
    case "csp":
      return {
        maxGain: premium,
        maxLoss: K - premium,
        breakevens: [K - premium],
      };
  }
}

// ── Multi-leg strategies ──────────────────────────────────────────────────────

interface MultiLegMeta {
  name: string;
  oneLiner: string;
  description: string;
}

const MULTI_LEG_META: Record<MultiLegType, MultiLegMeta> = {
  bear_call_spread: {
    name: "Bear Call Spread",
    oneLiner: "Bearish — sell an OTM call, buy a higher-strike call to cap risk.",
    description:
      "You sell a call at the short strike and buy a higher call (the wing) to limit upside risk. " +
      "You collect a net credit upfront. If the stock stays below the short strike at expiration, " +
      "both calls expire worthless and you keep the full credit. If it rises above the long strike, " +
      "you lose the wing width minus the credit. A defined-risk bearish trade.",
  },
  short_strangle: {
    name: "Short Strangle",
    oneLiner: "Neutral — sell an OTM call and OTM put, profit if the stock stays between the short strikes.",
    description:
      "You simultaneously sell an out-of-the-money call and put, collecting both premiums. " +
      "Max gain is the combined credit if the stock expires between the two short strikes. " +
      "Losses are unlimited in either direction — the call side has no cap, and the put side grows " +
      "as the stock falls toward zero. Thrives in high-IV environments but requires active management.",
  },
  iron_condor: {
    name: "Iron Condor",
    oneLiner: "Neutral — a short strangle with protective wings on both sides for fully defined risk.",
    description:
      "A short call spread plus a short put spread. You collect a net credit and profit if the stock " +
      "stays between the short strikes at expiration. The wings (long options) cap your maximum loss at " +
      "wing width minus the credit. Less premium than a naked strangle, but risk is fully defined.",
  },
};

interface MultiLegStats {
  netCredit: number;
  maxGain: number;
  maxLoss: number | null;  // null = unlimited
  breakevens: number[];
}

function isMultiLeg(s: StrategyType | MultiLegType): s is MultiLegType {
  return s === "bear_call_spread" || s === "short_strangle" || s === "iron_condor";
}

/** Single-leg P&L per share before expiration using Black-Scholes for the option. */
function payoffBSPS(
  strategy: StrategyType,
  K: number, premium: number, currentPrice: number, S: number,
  T: number, sigma: number, r: number,
): number {
  if (T <= 0) return payoffPS(strategy, K, premium, currentPrice, S);
  const bsC = blackScholes("call", S, K, T, sigma, r);
  const bsP = blackScholes("put",  S, K, T, sigma, r);
  switch (strategy) {
    case "long_call":    return bsC - premium;
    case "long_put":     return bsP - premium;
    case "covered_call": return (S - currentPrice) + premium - bsC;
    case "csp":          return premium - bsP;
  }
}

// Custom Y-axis tick: signed (+/−), color-coded green/red
function PayoffYTick({
  x, y, payload,
}: {
  x?: number;
  y?: number;
  payload?: { value: number };
}) {
  if (x == null || y == null || !payload) return null;
  const v = payload.value;
  const color = v < 0 ? "hsl(var(--destructive))" : v > 0 ? "hsl(var(--success))" : "hsl(var(--muted-foreground))";
  const abs = Math.abs(Math.round(v)).toLocaleString("en-US");
  const label = v >= 0 ? `+$${abs}` : `-$${abs}`;
  return (
    <text x={x} y={y} fill={color} fontSize={10} textAnchor="end" dominantBaseline="middle">
      {label}
    </text>
  );
}

function PayoffTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{
    name: string;
    dataKey: string;
    value: number;
    color: string;
    payload: { price: number };
  }>;
}) {
  if (!active || !payload?.length) return null;
  const price = payload[0].payload.price;
  return (
    <div className="rounded border bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 shadow px-3 py-2 text-xs space-y-0.5">
      <p className="text-zinc-500 dark:text-zinc-400">Stock: <strong className="text-zinc-900 dark:text-zinc-100">${price.toFixed(2)}</strong></p>
      {payload.filter(p => p.value != null).map((p) => {
        const abs = Math.abs(p.value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return (
          <p key={p.dataKey} style={{ color: p.color }} className="font-medium">
            {p.name}: {p.value >= 0 ? "+" : "−"}${abs}
          </p>
        );
      })}
    </div>
  );
}

function StrategyCard({
  strategy,
  data,
}: {
  strategy: StrategyType;
  data: StrategyData;
}) {
  const meta = STRATEGY_META[strategy];
  const cp = data.current_price ?? 0;

  const validStrikes = useMemo<StrikeData[]>(() => {
    return data.strikes
      .filter((s) => (meta.usesCall ? s.call_mid != null : s.put_mid != null))
      .sort((a, b) => a.strike - b.strike);
  }, [data.strikes, meta.usesCall]);

  const initialStrike = useMemo(() => {
    const atm = validStrikes.find((s) => s.is_atm);
    return atm?.strike ?? validStrikes[Math.floor(validStrikes.length / 2)]?.strike ?? 0;
  }, [validStrikes]);

  const [selectedStrike, setSelectedStrike] = useState<number>(initialStrike);
  const [contracts, setContracts] = useState<number>(1);
  const [dateOffset, setDateOffset] = useState<number>(0); // 0 = today, totalDays = expiry
  const [scrubPrice, setScrubPrice] = useState<number>(cp);

  useEffect(() => {
    setSelectedStrike(initialStrike);
  }, [initialStrike]);

  const strikeObj = validStrikes.find((s) => s.strike === selectedStrike);
  const premium = (meta.usesCall ? strikeObj?.call_mid : strikeObj?.put_mid) ?? 0;

  // IV for BS pricing: use per-strike IV, fall back to ATM IV, then a default
  const atmIVData = data.strikes.find((s) => s.is_atm);
  const sigma = (
    meta.usesCall
      ? (strikeObj?.call_iv ?? atmIVData?.call_iv ?? BS_IV_DEFAULT)
      : (strikeObj?.put_iv  ?? atmIVData?.put_iv  ?? BS_IV_DEFAULT)
  );

  const T_today = data.expiration
    ? Math.max(0, (dateMs(data.expiration) - Date.now()) / MS_PER_YEAR)
    : 0;
  const T_earnings = (data.earnings_date && data.expiration)
    ? Math.max(0, (dateMs(data.expiration) - dateMs(data.earnings_date)) / MS_PER_YEAR)
    : null;
  const showEarnings = T_earnings !== null && T_earnings > 0 && T_earnings < T_today;

  // Date slider: 0=today → totalDays=expiry; T_slider is T at the selected date
  const totalDays = Math.max(1, Math.round(T_today * 365.25));
  const T_slider = Math.max(0, (totalDays - dateOffset) / 365.25);
  const selectedDateMs = Date.now() + dateOffset * 86400000;
  const selectedDateStr = new Date(selectedDateMs).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const daysToExpiry = Math.max(0, totalDays - dateOffset);
  const earningsDateMs = data.earnings_date ? dateMs(data.earnings_date) : null;
  // Disclaimer: show whenever the slider is at or before earnings (IV held constant is misleading then)
  const showDisclaimer = showEarnings && earningsDateMs != null && selectedDateMs <= earningsDateMs;

  const mult = contracts * 100;

  // x-axis range: implied range ± 30% of range width, extended if breakeven falls outside
  const xRange = useMemo(() => {
    const irLo = data.implied_range_low;
    const irHi = data.implied_range_high;
    let lo: number, hi: number;
    if (irLo != null && irHi != null) {
      const pad = (irHi - irLo) * 0.30;
      lo = irLo - pad;
      hi = irHi + pad;
    } else {
      lo = cp * 0.80;
      hi = cp * 1.20;
    }
    // Extend if the strategy's breakeven would fall outside the frame
    const beValues: number[] = [];
    if (strategy === "long_call")    beValues.push(selectedStrike + premium);
    if (strategy === "long_put")     beValues.push(selectedStrike - premium);
    if (strategy === "covered_call") beValues.push(cp - premium);
    if (strategy === "csp")          beValues.push(selectedStrike - premium);
    for (const be of beValues) {
      if (be < lo) lo = be - (hi - lo) * 0.05;
      if (be > hi) hi = be + (hi - lo) * 0.05;
    }
    return { lo, hi };
  }, [data.implied_range_low, data.implied_range_high, cp, strategy, selectedStrike, premium]);

  // Live chartData: recomputes on every slider tick (~100 BS evals, <1 ms)
  const chartData = useMemo(() => {
    if (!cp) return [];
    const { lo, hi } = xRange;
    return Array.from({ length: 100 }, (_, i) => {
      const S = lo + (i / 99) * (hi - lo);
      const pnl = T_slider > 0
        ? payoffBSPS(strategy, selectedStrike, premium, cp, S, T_slider, sigma, BS_R) * mult
        : payoffPS(strategy, selectedStrike, premium, cp, S) * mult;
      return { price: parseFloat(S.toFixed(2)), pnl: parseFloat(pnl.toFixed(2)) };
    });
  }, [strategy, selectedStrike, premium, cp, mult, xRange, T_slider, sigma]);

  const stats = useMemo(
    () => strategyStats(strategy, selectedStrike, premium, cp),
    [strategy, selectedStrike, premium, cp],
  );

  if (!validStrikes.length || !cp) {
    return (
      <div className="rounded-lg border bg-card px-5 py-4 text-sm text-muted-foreground">
        No valid contracts available for {meta.name}.
      </div>
    );
  }

  // Stable Y-axis: computed from expiry+today endpoints so axis doesn't jump as slider moves
  const yDomain = useMemo<[number, number]>(() => {
    if (!cp) return [-100, 100];
    const { lo, hi } = xRange;
    const vals: number[] = [];
    for (let i = 0; i < 100; i++) {
      const S = lo + (i / 99) * (hi - lo);
      vals.push(payoffPS(strategy, selectedStrike, premium, cp, S) * mult);
      if (T_today > 0) vals.push(payoffBSPS(strategy, selectedStrike, premium, cp, S, T_today, sigma, BS_R) * mult);
    }
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const pad = (yMax - yMin) * 0.15 || 1;
    return [yMin - pad, yMax + pad];
  }, [strategy, selectedStrike, premium, cp, mult, xRange, T_today, sigma]);

  const xLo = chartData[0]?.price ?? 0;
  const xHi = chartData[chartData.length - 1]?.price ?? 0;
  const scrubPoint = chartData.length
    ? chartData.reduce((best, d) => Math.abs(d.price - scrubPrice) < Math.abs(best.price - scrubPrice) ? d : best)
    : null;
  const effectivePrice = scrubPoint?.price ?? scrubPrice;
  const scrubPnl: number | null = scrubPoint?.pnl ?? null;

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-3">
      <div>
        <h4 className="font-semibold text-sm">{meta.name}</h4>
        <p className="text-xs text-muted-foreground mt-0.5">{meta.oneLiner}</p>
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed">{meta.description}</p>

      {/* Strike + contracts selectors */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Strike:</span>
          <select
            value={selectedStrike}
            onChange={(e) => setSelectedStrike(parseFloat(e.target.value))}
            className="rounded-md border bg-background px-2 py-1 text-sm"
          >
            {validStrikes.map((s) => {
              const mid = meta.usesCall ? s.call_mid : s.put_mid;
              return (
                <option key={s.strike} value={s.strike}>
                  ${s.strike.toFixed(0)}{s.is_atm ? " (ATM)" : ""}{" "}
                  — {meta.usesCall ? "call" : "put"} ${mid?.toFixed(2) ?? "—"}
                </option>
              );
            })}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Contracts:</span>
          <input
            type="number"
            min={1}
            max={500}
            value={contracts}
            onChange={(e) => setContracts(Math.max(1, parseInt(e.target.value) || 1))}
            className="rounded-md border bg-background px-2 py-1 text-sm w-16 tabular-nums"
          />
        </div>
        {data.expiration && (
          <span className="text-xs text-muted-foreground">expiry {data.expiration}</span>
        )}
      </div>

      {/* ── Hero P&L ──────────────────────────────────────────────── */}
      <div className="py-1">
        <p className="text-xs text-muted-foreground mb-1.5">
          {data.symbol} at ${effectivePrice.toFixed(2)}
          {" · "}
          {daysToExpiry === 0 ? "At expiration" : selectedDateStr}
        </p>
        <p className={cn(
          "text-4xl font-bold tabular-nums tracking-tight leading-none",
          scrubPnl == null
            ? "text-muted-foreground"
            : scrubPnl >= 0
              ? "text-success"
              : "text-destructive",
        )}>
          {scrubPnl == null
            ? "—"
            : `${scrubPnl >= 0 ? "+" : "−"}$${Math.abs(scrubPnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        </p>
      </div>

      {/* ── Live payoff chart ──────────────────────────────────────── */}
      <ResponsiveContainer width="100%" height={200}>
        <LineChart
          data={chartData}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          onMouseMove={(e) => {
            if (e.activeLabel != null) {
              const p = parseFloat(String(e.activeLabel));
              if (!isNaN(p)) setScrubPrice(p);
            }
          }}
          onClick={(e) => {
            if (e.activeLabel != null) {
              const p = parseFloat(String(e.activeLabel));
              if (!isNaN(p)) setScrubPrice(p);
            }
          }}
        >
          <CartesianGrid
            strokeDasharray="2 6"
            stroke="hsl(var(--border))"
            strokeOpacity={0.4}
            vertical={false}
          />
          <XAxis
            dataKey="price"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={yDomain}
            tick={<PayoffYTick />}
            axisLine={false}
            tickLine={false}
            width={68}
          />

          {/* Implied range band — very faint */}
          {data.implied_range_low != null && data.implied_range_high != null && (
            <ReferenceArea
              x1={Math.max(data.implied_range_low, xLo)}
              x2={Math.min(data.implied_range_high, xHi)}
              fill="hsl(var(--muted))"
              fillOpacity={0.2}
            />
          )}

          {/* Zero line */}
          <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />

          {/* Current price */}
          <ReferenceLine
            x={cp}
            stroke="hsl(var(--muted-foreground))"
            strokeWidth={1}
            strokeDasharray="3 5"
            strokeOpacity={0.6}
            label={{ value: "Current", position: "insideBottomRight", fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
          />

          {/* Price scrubber */}
          <ReferenceLine
            x={effectivePrice}
            stroke="hsl(var(--foreground))"
            strokeWidth={1.5}
            strokeOpacity={0.85}
          />

          {/* Breakeven(s) */}
          {stats.breakevens.map((be, i) => (
            <ReferenceLine
              key={i}
              x={be}
              stroke="hsl(var(--success))"
              strokeWidth={1}
              strokeDasharray="3 5"
              strokeOpacity={0.8}
              label={{ value: "B/E", position: "insideTopRight", fontSize: 9, fill: "hsl(var(--success))" }}
            />
          ))}

          {/* P&L curve — redraws live with each slider tick */}
          <Line
            dataKey="pnl"
            stroke="hsl(var(--cool))"
            strokeWidth={2.5}
            dot={false}
            activeDot={false}
            type={T_slider === 0 ? "linear" : "monotone"}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>

      {/* ── Date slider ────────────────────────────────────────────── */}
      <div className="space-y-1.5 px-0.5">
        <input
          type="range"
          min={0}
          max={totalDays}
          value={dateOffset}
          onChange={(e) => setDateOffset(parseInt(e.target.value))}
          className="w-full h-1 rounded-full appearance-none cursor-pointer"
          style={{ accentColor: "hsl(var(--foreground))" }}
        />
        <div className="flex justify-between items-baseline text-[10px]">
          <span className="text-muted-foreground">Today</span>
          <span className="font-medium text-foreground">
            {daysToExpiry === 0
              ? "At expiration"
              : `${selectedDateStr} · ${daysToExpiry}d to expiry`}
          </span>
          <span className="text-muted-foreground">Expiry</span>
        </div>
      </div>

      {/* IV-crush disclaimer — shows when slider is at or before earnings date */}
      {showDisclaimer && (
        <Callout severity="info" compact>
          This curve holds today&apos;s implied volatility constant.
          In practice, IV typically collapses after an earnings release — option values at
          or around earnings will likely be lower than shown.
        </Callout>
      )}

      {/* Key stats — dollar figures scaled to contract size; breakeven stays as stock price */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm pt-1 border-t">
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Premium {meta.usesCall ? "paid" : "received"}:</span>
          <span className="font-medium tabular-nums">
            ${(premium * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        {stats.breakevens.map((be, i) => (
          <div key={i} className="flex justify-between gap-2">
            <span className="text-muted-foreground">Breakeven (stock price):</span>
            <span className="font-medium tabular-nums">${be.toFixed(2)}</span>
          </div>
        ))}
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max gain:</span>
          <span className="font-medium tabular-nums text-green-600 dark:text-green-400">
            {stats.maxGain == null
              ? "Unlimited ↑"
              : `+$${(stats.maxGain * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max loss:</span>
          <span className="font-medium tabular-nums text-red-600 dark:text-red-400">
            −${(stats.maxLoss * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
      </div>
    </div>
  );
}

function MultiLegStrategyCard({
  strategy,
  data,
}: {
  strategy: MultiLegType;
  data: StrategyData;
}) {
  const meta = MULTI_LEG_META[strategy];
  const cp = data.current_price ?? 0;

  const callStrikes = useMemo<StrikeData[]>(
    () => data.strikes.filter((s) => s.call_mid != null).sort((a, b) => a.strike - b.strike),
    [data.strikes],
  );
  const putStrikes = useMemo<StrikeData[]>(
    () => data.strikes.filter((s) => s.put_mid != null).sort((a, b) => a.strike - b.strike),
    [data.strikes],
  );

  const irLo = data.implied_range_low;
  const irHi = data.implied_range_high;

  // Default short call: nearest call >= irHi, or ATM
  const defaultSC = useMemo(() => {
    if (irHi != null) {
      const found = callStrikes.find((s) => s.strike >= irHi);
      if (found) return found.strike;
    }
    return (
      callStrikes.find((s) => s.is_atm)?.strike ??
      callStrikes[Math.floor(callStrikes.length / 2)]?.strike ??
      0
    );
  }, [callStrikes, irHi]);

  // Default short put: nearest put <= irLo, or ATM
  const defaultSP = useMemo(() => {
    if (irLo != null) {
      const found = [...putStrikes].reverse().find((s) => s.strike <= irLo);
      if (found) return found.strike;
    }
    return (
      putStrikes.find((s) => s.is_atm)?.strike ??
      putStrikes[Math.floor(putStrikes.length / 2)]?.strike ??
      0
    );
  }, [putStrikes, irLo]);

  const [shortCallStrike, setShortCallStrike] = useState<number>(defaultSC);
  const [shortPutStrike, setShortPutStrike] = useState<number>(defaultSP);
  const [contracts, setContracts] = useState<number>(1);
  const [dateOffset, setDateOffset] = useState<number>(0);
  const [scrubPrice, setScrubPrice] = useState<number>(cp);

  useEffect(() => { setShortCallStrike(defaultSC); }, [defaultSC]);
  useEffect(() => { setShortPutStrike(defaultSP); }, [defaultSP]);

  const mult = contracts * 100;

  const T_today = data.expiration
    ? Math.max(0, (dateMs(data.expiration) - Date.now()) / MS_PER_YEAR)
    : 0;
  const T_earnings = (data.earnings_date && data.expiration)
    ? Math.max(0, (dateMs(data.expiration) - dateMs(data.earnings_date)) / MS_PER_YEAR)
    : null;
  const showEarnings = T_earnings !== null && T_earnings > 0 && T_earnings < T_today;

  // Date slider derived values
  const totalDays = Math.max(1, Math.round(T_today * 365.25));
  const T_slider = Math.max(0, (totalDays - dateOffset) / 365.25);
  const selectedDateMs = Date.now() + dateOffset * 86400000;
  const selectedDateStr = new Date(selectedDateMs).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const daysToExpiry = Math.max(0, totalDays - dateOffset);
  const earningsDateMs = data.earnings_date ? dateMs(data.earnings_date) : null;
  const showDisclaimer = showEarnings && earningsDateMs != null && selectedDateMs <= earningsDateMs;

  const { legs, stats } = useMemo<{ legs: Leg[]; stats: MultiLegStats }>(() => {
    const scObj = callStrikes.find((s) => s.strike === shortCallStrike);
    const spObj = putStrikes.find((s) => s.strike === shortPutStrike);
    // Wings: snap to the valid strike nearest to ±$10 from the short strike.
    // Dollar-width targeting is robust to missing strikes; index-stepping is not.
    const TARGET_WING = 10;

    const lcObj = scObj
      ? callStrikes
          .filter((s) => s.strike > shortCallStrike)
          .reduce<StrikeData | null>(
            (best, s) =>
              !best ||
              Math.abs(s.strike - (shortCallStrike + TARGET_WING)) <
                Math.abs(best.strike - (shortCallStrike + TARGET_WING))
                ? s
                : best,
            null,
          )
      : null;

    const lpObj = spObj
      ? putStrikes
          .filter((s) => s.strike < shortPutStrike)
          .reduce<StrikeData | null>(
            (best, s) =>
              !best ||
              Math.abs(s.strike - (shortPutStrike - TARGET_WING)) <
                Math.abs(best.strike - (shortPutStrike - TARGET_WING))
                ? s
                : best,
            null,
          )
      : null;

    // IV fallbacks: per-strike IV, then ATM IV, then global default
    const atmSd = data.strikes.find((s) => s.is_atm);
    const fbC = atmSd?.call_iv ?? BS_IV_DEFAULT;
    const fbP = atmSd?.put_iv  ?? BS_IV_DEFAULT;

    let legs: Leg[] = [];
    let netCredit = 0;
    let maxGain = 0;
    let maxLoss: number | null = 0;
    let breakevens: number[] = [];

    if (strategy === "bear_call_spread" && scObj && lcObj) {
      netCredit = scObj.call_mid! - lcObj.call_mid!;
      legs = [
        { kind: "call", K: scObj.strike, mid: scObj.call_mid!, sigma: scObj.call_iv ?? fbC, dir: -1, label: `Short call $${scObj.strike.toFixed(0)}` },
        { kind: "call", K: lcObj.strike, mid: lcObj.call_mid!, sigma: lcObj.call_iv ?? fbC, dir: 1,  label: `Long call $${lcObj.strike.toFixed(0)} (wing)` },
      ];
      maxGain = netCredit;
      maxLoss = lcObj.strike - scObj.strike - netCredit;
      breakevens = [scObj.strike + netCredit];
    } else if (strategy === "short_strangle" && scObj && spObj) {
      netCredit = scObj.call_mid! + spObj.put_mid!;
      legs = [
        { kind: "call", K: scObj.strike, mid: scObj.call_mid!, sigma: scObj.call_iv ?? fbC, dir: -1, label: `Short call $${scObj.strike.toFixed(0)}` },
        { kind: "put",  K: spObj.strike, mid: spObj.put_mid!,  sigma: spObj.put_iv  ?? fbP, dir: -1, label: `Short put $${spObj.strike.toFixed(0)}` },
      ];
      maxGain = netCredit;
      maxLoss = null;
      breakevens = [spObj.strike - netCredit, scObj.strike + netCredit];
    } else if (strategy === "iron_condor" && scObj && lcObj && spObj && lpObj) {
      netCredit = scObj.call_mid! + spObj.put_mid! - lcObj.call_mid! - lpObj.put_mid!;
      legs = [
        { kind: "call", K: scObj.strike, mid: scObj.call_mid!, sigma: scObj.call_iv ?? fbC, dir: -1, label: `Short call $${scObj.strike.toFixed(0)}` },
        { kind: "call", K: lcObj.strike, mid: lcObj.call_mid!, sigma: lcObj.call_iv ?? fbC, dir: 1,  label: `Long call $${lcObj.strike.toFixed(0)} (wing)` },
        { kind: "put",  K: spObj.strike, mid: spObj.put_mid!,  sigma: spObj.put_iv  ?? fbP, dir: -1, label: `Short put $${spObj.strike.toFixed(0)}` },
        { kind: "put",  K: lpObj.strike, mid: lpObj.put_mid!,  sigma: lpObj.put_iv  ?? fbP, dir: 1,  label: `Long put $${lpObj.strike.toFixed(0)} (wing)` },
      ];
      maxGain = netCredit;
      const callWingWidth = lcObj.strike - scObj.strike;
      const putWingWidth = spObj.strike - lpObj.strike;
      maxLoss = Math.max(callWingWidth, putWingWidth) - netCredit;
      breakevens = [spObj.strike - netCredit, scObj.strike + netCredit];
    }

    return { legs, stats: { netCredit, maxGain, maxLoss, breakevens } };
  }, [strategy, shortCallStrike, shortPutStrike, callStrikes, putStrikes]);

  // x-range: implied range ±30%, extended to include all strikes and breakevens
  const xRange = useMemo(() => {
    let lo: number, hi: number;
    if (irLo != null && irHi != null) {
      const pad = (irHi - irLo) * 0.30;
      lo = irLo - pad;
      hi = irHi + pad;
    } else {
      lo = cp * 0.80;
      hi = cp * 1.20;
    }
    for (const leg of legs) {
      if (leg.K < lo) lo = leg.K - (hi - lo) * 0.05;
      if (leg.K > hi) hi = leg.K + (hi - lo) * 0.05;
    }
    for (const be of stats.breakevens) {
      if (be < lo) lo = be - (hi - lo) * 0.05;
      if (be > hi) hi = be + (hi - lo) * 0.05;
    }
    return { lo, hi };
  }, [irLo, irHi, cp, legs, stats.breakevens]);

  // Live chartData: single pnl series, recomputes with each slider tick
  const chartData = useMemo(() => {
    if (!cp || !legs.length) return [];
    const { lo, hi } = xRange;
    return Array.from({ length: 100 }, (_, i) => {
      const S = lo + (i / 99) * (hi - lo);
      const pnl = T_slider > 0
        ? multiLegPayoffBSPS(legs, S, T_slider, BS_R) * mult
        : multiLegPayoffPS(legs, S) * mult;
      return { price: parseFloat(S.toFixed(2)), pnl: parseFloat(pnl.toFixed(2)) };
    });
  }, [legs, cp, mult, xRange, T_slider]);

  if (!callStrikes.length || !cp) {
    return (
      <div className="rounded-lg border bg-card px-5 py-4 text-sm text-muted-foreground">
        No valid contracts available for {meta.name}.
      </div>
    );
  }

  // Stable Y-axis: computed from expiry+today only so axis stays fixed as slider moves
  const yDomain = useMemo<[number, number]>(() => {
    if (!cp || !legs.length) return [-100, 100];
    const { lo, hi } = xRange;
    const vals: number[] = [];
    for (let i = 0; i < 100; i++) {
      const S = lo + (i / 99) * (hi - lo);
      vals.push(multiLegPayoffPS(legs, S) * mult);
      if (T_today > 0) vals.push(multiLegPayoffBSPS(legs, S, T_today, BS_R) * mult);
    }
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const pad = (yMax - yMin) * 0.15 || 1;
    return [yMin - pad, yMax + pad];
  }, [legs, cp, mult, xRange, T_today]);

  const xLo = chartData[0]?.price ?? 0;
  const xHi = chartData[chartData.length - 1]?.price ?? 0;
  const hasShortPut = strategy === "short_strangle" || strategy === "iron_condor";
  const scrubPoint = chartData.length
    ? chartData.reduce((best, d) => Math.abs(d.price - scrubPrice) < Math.abs(best.price - scrubPrice) ? d : best)
    : null;
  const effectivePrice = scrubPoint?.price ?? scrubPrice;
  const scrubPnl: number | null = scrubPoint?.pnl ?? null;

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-3">
      <div>
        <h4 className="font-semibold text-sm">{meta.name}</h4>
        <p className="text-xs text-muted-foreground mt-0.5">{meta.oneLiner}</p>
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed">{meta.description}</p>

      {/* Strike selectors */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Short call:</span>
          <select
            value={shortCallStrike}
            onChange={(e) => setShortCallStrike(parseFloat(e.target.value))}
            className="rounded-md border bg-background px-2 py-1 text-sm"
          >
            {callStrikes.map((s) => (
              <option key={s.strike} value={s.strike}>
                ${s.strike.toFixed(0)}{s.is_atm ? " (ATM)" : ""} — call ${s.call_mid?.toFixed(2) ?? "—"}
              </option>
            ))}
          </select>
        </div>
        {hasShortPut && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground shrink-0">Short put:</span>
            <select
              value={shortPutStrike}
              onChange={(e) => setShortPutStrike(parseFloat(e.target.value))}
              className="rounded-md border bg-background px-2 py-1 text-sm"
            >
              {putStrikes.map((s) => (
                <option key={s.strike} value={s.strike}>
                  ${s.strike.toFixed(0)}{s.is_atm ? " (ATM)" : ""} — put ${s.put_mid?.toFixed(2) ?? "—"}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Contracts:</span>
          <input
            type="number"
            min={1}
            max={500}
            value={contracts}
            onChange={(e) => setContracts(Math.max(1, parseInt(e.target.value) || 1))}
            className="rounded-md border bg-background px-2 py-1 text-sm w-16 tabular-nums"
          />
        </div>
        {data.expiration && (
          <span className="text-xs text-muted-foreground">expiry {data.expiration}</span>
        )}
      </div>

      {/* Legs summary */}
      {legs.length > 0 && (
        <div className="rounded-md bg-muted/40 px-3 py-2 text-xs space-y-0.5">
          {legs.map((leg, i) => (
            <div key={i} className="flex justify-between text-muted-foreground">
              <span>{leg.label}</span>
              <span className="tabular-nums">${leg.mid.toFixed(2)} mid</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Hero P&L ──────────────────────────────────────────────── */}
      <div className="py-1">
        <p className="text-xs text-muted-foreground mb-1.5">
          {data.symbol} at ${effectivePrice.toFixed(2)}
          {" · "}
          {daysToExpiry === 0 ? "At expiration" : selectedDateStr}
        </p>
        <p
          className={cn(
            "text-4xl font-bold tabular-nums tracking-tight leading-none",
            scrubPnl == null
              ? "text-muted-foreground"
              : scrubPnl >= 0
                ? "text-success"
                : "text-destructive",
          )}
        >
          {scrubPnl == null
            ? "—"
            : `${scrubPnl >= 0 ? "+" : "−"}$${Math.abs(scrubPnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        </p>
      </div>

      {/* ── Live payoff chart ──────────────────────────────────────── */}
      <ResponsiveContainer width="100%" height={200}>
        <LineChart
          data={chartData}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          onMouseMove={(e) => {
            if (e.activeLabel != null) {
              const p = parseFloat(String(e.activeLabel));
              if (!isNaN(p)) setScrubPrice(p);
            }
          }}
          onClick={(e) => {
            if (e.activeLabel != null) {
              const p = parseFloat(String(e.activeLabel));
              if (!isNaN(p)) setScrubPrice(p);
            }
          }}
        >
          <CartesianGrid strokeDasharray="2 6" stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
          <XAxis
            dataKey="price"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={yDomain}
            tick={<PayoffYTick />}
            axisLine={false}
            tickLine={false}
            width={68}
          />

          {/* Implied range band */}
          {data.implied_range_low != null && data.implied_range_high != null && (
            <ReferenceArea
              x1={Math.max(data.implied_range_low, xLo)}
              x2={Math.min(data.implied_range_high, xHi)}
              fill="hsl(var(--muted))"
              fillOpacity={0.2}
            />
          )}

          {/* Zero line */}
          <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />

          {/* Current price */}
          <ReferenceLine
            x={cp}
            stroke="hsl(var(--muted-foreground))"
            strokeWidth={1}
            strokeDasharray="3 5"
            strokeOpacity={0.6}
            label={{ value: "Current", position: "insideBottomRight", fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
          />

          {/* Price scrubber */}
          <ReferenceLine
            x={effectivePrice}
            stroke="hsl(var(--foreground))"
            strokeWidth={1.5}
            strokeOpacity={0.85}
          />

          {/* Breakevens */}
          {stats.breakevens.map((be, i) => (
            <ReferenceLine
              key={i}
              x={be}
              stroke="hsl(var(--success))"
              strokeWidth={1}
              strokeDasharray="3 5"
              label={{ value: "B/E", position: "insideTopRight", fontSize: 9, fill: "hsl(var(--success))" }}
            />
          ))}

          <Line
            dataKey="pnl"
            stroke="hsl(var(--cool))"
            strokeWidth={2.5}
            dot={false}
            activeDot={false}
            type={T_slider === 0 ? "linear" : "monotone"}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>

      {/* ── Date slider ────────────────────────────────────────────── */}
      <div className="space-y-1.5 px-0.5">
        <input
          type="range"
          min={0}
          max={totalDays}
          value={dateOffset}
          onChange={(e) => setDateOffset(parseInt(e.target.value))}
          className="w-full h-1 rounded-full appearance-none cursor-pointer"
          style={{ accentColor: "hsl(var(--foreground))" }}
        />
        <div className="flex justify-between items-baseline text-[10px]">
          <span className="text-muted-foreground">Today</span>
          <span className="font-medium text-foreground">
            {daysToExpiry === 0
              ? "At expiration"
              : `${selectedDateStr} · ${daysToExpiry}d to expiry`}
          </span>
          <span className="text-muted-foreground">Expiry</span>
        </div>
      </div>

      {/* IV-crush disclaimer — shows when slider is at or before earnings date */}
      {showDisclaimer && (
        <Callout severity="info" compact>
          This curve holds today&apos;s implied volatility constant.
          It does not model the IV crush that typically follows an earnings release — real
          post-earnings option values will likely be lower.
        </Callout>
      )}

      {/* Key stats */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm pt-1 border-t">
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Net credit:</span>
          <span className="font-medium tabular-nums text-green-600 dark:text-green-400">
            +${(stats.netCredit * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        {stats.breakevens.map((be, i) => (
          <div key={i} className="flex justify-between gap-2">
            <span className="text-muted-foreground">
              Breakeven{stats.breakevens.length > 1 ? (be < cp ? " (down)" : " (up)") : " (stock price)"}:
            </span>
            <span className="font-medium tabular-nums">${be.toFixed(2)}</span>
          </div>
        ))}
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max gain:</span>
          <span className="font-medium tabular-nums text-green-600 dark:text-green-400">
            +${(stats.maxGain * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max loss:</span>
          <span className="font-medium tabular-nums text-red-600 dark:text-red-400">
            {stats.maxLoss == null
              ? "Unlimited ↓"
              : `−$${(stats.maxLoss * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          </span>
        </div>
      </div>
    </div>
  );
}

function StrategyExplainer({ data, symbol }: { data: StrategyData; symbol: string }) {
  const [open, setOpen] = useState(false);
  const [outlook, setOutlook] = useState<Outlook>("bullish");

  return (
    <div className="mt-6 rounded-lg border bg-card overflow-visible">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-medium hover:bg-muted/30 transition-colors text-left"
        aria-expanded={open}
      >
        <span>Directional strategy explainer — {symbol}</span>
        <span className="text-muted-foreground text-xs shrink-0 ml-4">{open ? "▲ Collapse" : "▼ Expand"}</span>
      </button>

      {open && (
        <div className="border-t px-5 py-4 space-y-5">
          <p className="text-xs text-muted-foreground italic leading-relaxed">
            Educational only — not investment advice. Payoff diagrams show at-expiration outcomes
            per share using real bid/ask mid-prices from the {data.expiration} expiration.
            Options are leveraged instruments; actual outcomes depend on timing, assignment, and
            transaction costs.
          </p>

          {/* Outlook tabs */}
          <div className="flex gap-1">
            {(["bullish", "bearish", "neutral"] as Outlook[]).map((o) => (
              <button
                key={o}
                onClick={() => setOutlook(o)}
                className={cn(
                  "px-3 py-1 rounded text-xs font-medium capitalize transition-colors",
                  outlook === o
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted",
                )}
              >
                {o.charAt(0).toUpperCase() + o.slice(1)}
              </button>
            ))}
          </div>

          {/* Implied range legend */}
          {data.implied_range_low != null && data.implied_range_high != null && (
            <p className="text-xs text-muted-foreground">
              <span className="inline-block w-3 h-3 rounded-sm bg-muted opacity-80 mr-1.5 align-middle" />
              Shaded band = implied range ${data.implied_range_low.toFixed(2)}–${data.implied_range_high.toFixed(2)} by {data.expiration}
            </p>
          )}

          {/* Strategy cards */}
          <div className="space-y-4">
            {OUTLOOK_STRATEGIES[outlook].map((s) =>
              isMultiLeg(s) ? (
                <MultiLegStrategyCard key={s} strategy={s} data={data} />
              ) : (
                <StrategyCard key={s} strategy={s as StrategyType} data={data} />
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}


// ── Status types ──────────────────────────────────────────────────────────────

type TickerStatus   = "loading" | "found" | "missing" | "error";
type SectionStatus  = "loading" | "done" | "error";

// ── Realized Volatility Panel ─────────────────────────────────────────────────

function RealizedVolPanel({ rv }: { rv: RealizedVol }) {
  const pct = (v: number | null, d = 1) =>
    v == null ? "—" : `${(v * 100).toFixed(d)}%`;

  const rank = rv.rv_rank ?? 0;

  const { text: interp, color: interpColor } =
    rank < 25
      ? {
          text: "Vol is quieter than usual for this stock — it\u2019s moving less than its own norm over the past year.",
          color: "text-muted-foreground",
        }
      : rank < 70
      ? {
          text: "Vol is normal for this stock — near its typical level over the past year.",
          color: "text-muted-foreground",
        }
      : rank < 90
      ? {
          text: "Vol is elevated for this stock — it\u2019s moving more than its own norm over the past year.",
          color: "text-amber-600 dark:text-amber-400",
        }
      : {
          text: "Vol is extreme for this stock — it\u2019s moving much more than usual compared to its own past year.",
          color: "text-primary",
        };

  const gaugeColor =
    rank < 25 ? "bg-muted-foreground/60" : rank < 70 ? "bg-foreground/60" : rank < 90 ? "bg-amber-500" : "bg-primary";

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-0.5">
            Realized-vol rank
          </p>
          <p className="text-3xl font-bold tabular-nums leading-none">
            {rv.rv_rank?.toFixed(1) ?? "—"}
          </p>
          {rv.rv_rank != null && (
            <p className={cn("text-sm font-medium mt-0.5", rvRankShort(rv.rv_rank).colorClass)}>
              {rvRankShort(rv.rv_rank).tag}
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground mb-0.5">{rv.window_days}-day realized vol</p>
          <p className="text-xl font-semibold tabular-nums">{pct(rv.current_rv)}</p>
        </div>
      </div>

      {/* Gauge */}
      <div className="space-y-1.5">
        <div className="relative h-2 rounded-full bg-muted overflow-hidden">
          <div
            className={cn("absolute left-0 top-0 h-full rounded-full", gaugeColor)}
            style={{ width: `${Math.min(100, rank)}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>0 — quiet for this stock</span>
          <span>100 — extreme for this stock</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 text-center pt-0.5">
        <div>
          <p className="text-xs text-muted-foreground mb-0.5">Percentile</p>
          <p className="text-lg font-semibold tabular-nums">{rv.rv_percentile?.toFixed(1) ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-0.5">1yr Low</p>
          <p className="text-lg font-semibold tabular-nums">{pct(rv.rv_min_1y)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-0.5">1yr High</p>
          <p className="text-lg font-semibold tabular-nums">{pct(rv.rv_max_1y)}</p>
        </div>
      </div>

      {/* Interpretation */}
      <p className={cn("text-sm leading-snug", interpColor)}>{interp}</p>

      {/* Honest disclaimer */}
      <p className="text-[11px] text-muted-foreground border-t pt-3 leading-relaxed">
        <strong>Realized (historical) volatility</strong> measures how much the stock has actually
        moved — annualized standard deviation of daily log returns over a {rv.window_days}-trading-day
        window, ranked against the trailing {rv.sample_days} trading days.{" "}
        <em>This is not implied volatility.</em> IV Rank (what the options market expects) requires
        daily IV snapshots — collection started today and will appear once enough history accrues
        (~3–6 months).
      </p>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TickerPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const upperSymbol = symbol.toUpperCase();

  const [ticker, setTicker]           = useState<Ticker | null>(null);
  const [tickerStatus, setTickerStatus] = useState<TickerStatus>("loading");
  const [tickerError, setTickerError]   = useState<string | null>(null);

  const [events, setEvents]             = useState<Event[]>([]);
  const [eventStatus, setEventStatus]   = useState<SectionStatus>("loading");
  const [eventError, setEventError]     = useState<string | null>(null);

  const [reactions, setReactions]         = useState<HistoricalReaction[]>([]);
  const [reactionStatus, setReactionStatus] = useState<SectionStatus>("loading");
  const [reactionError, setReactionError]   = useState<string | null>(null);
  const [reactionSummary, setReactionSummary] = useState<ReactionSummary | null>(null);

  const [quote, setQuote]             = useState<TickerQuote | null>(null);
  const [chartPeriod, setChartPeriod] = useState<ChartPeriod>("1y");
  const [chartStartPrice, setChartStartPrice] = useState<number | null>(null);
  const handleChartLoad = useCallback((startPrice: number | null) => {
    setChartStartPrice(startPrice);
  }, []);

  const [realizedVol, setRealizedVol]     = useState<RealizedVol | null>(null);
  const [rvStatus, setRvStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");
  const [optionsRead, setOptionsRead]     = useState<OptionsRead | null>(null);
  const [orStatus, setOrStatus]           = useState<"loading" | "done" | "error">("loading");

  const [expectedMove, setExpectedMove]   = useState<ExpectedMove | null>(null);
  const [emStatus, setEmStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");
  const [optionsChain, setOptionsChain]   = useState<OptionsChain | null>(null);
  const [ocStatus, setOcStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");
  const [selectedExpiration, setSelectedExpiration] = useState<string | null>(null);

  const [strategyData, setStrategyData]   = useState<StrategyData | null>(null);
  const [sdStatus, setSdStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");

  const [note, setNote]               = useState<ResearchNote | null>(null);
  const [noteStatus, setNoteStatus]   = useState<"loading" | "empty" | "done" | "error">("loading");
  const [verificationOpen, setVerificationOpen] = useState(false);

  const [news, setNews]               = useState<NewsResponse | null>(null);
  const [newsStatus, setNewsStatus]   = useState<"loading" | "done" | "empty" | "error">("loading");
  const [newsExpanded, setNewsExpanded] = useState(false);

  useEffect(() => {
    api.tickers
      .list(false)
      .then((tickers) => {
        const match = tickers.find((t) => t.symbol.toUpperCase() === upperSymbol);
        if (match) { setTicker(match); setTickerStatus("found"); }
        else { setTickerStatus("missing"); }
      })
      .catch((e: Error) => { setTickerError(e.message); setTickerStatus("error"); });
  }, [upperSymbol]);

  useEffect(() => {
    api.events
      .upcoming(upperSymbol, 60)
      .then((evts) => {
        setEvents([...evts].sort((a, b) => a.event_date.localeCompare(b.event_date)));
        setEventStatus("done");
      })
      .catch((e: Error) => { setEventError(e.message); setEventStatus("error"); });
  }, [upperSymbol]);

  useEffect(() => {
    api.reactions
      .list({ symbol: upperSymbol, event_type: "earnings" })
      .then((rows) => { setReactions(rows); setReactionStatus("done"); })
      .catch((e: Error) => { setReactionError(e.message); setReactionStatus("error"); });
    api.reactions
      .summary(upperSymbol)
      .then(setReactionSummary)
      .catch(() => setReactionSummary(null));
  }, [upperSymbol]);

  useEffect(() => {
    api.tickers.quote(upperSymbol).then(setQuote).catch(() => null);
  }, [upperSymbol]);

  useEffect(() => {
    api.tickers.realizedVol(upperSymbol)
      .then((data) => {
        setRealizedVol(data);
        setRvStatus(data.current_rv != null ? "done" : "empty");
      })
      .catch(() => setRvStatus("error"));
  }, [upperSymbol]);

  useEffect(() => {
    setNewsExpanded(false);
    api.tickers.news(upperSymbol)
      .then((data) => {
        setNews(data);
        setNewsStatus(data.items.length > 0 ? "done" : "empty");
      })
      .catch(() => setNewsStatus("error"));
  }, [upperSymbol]);

  useEffect(() => {
    api.tickers.optionsRead(upperSymbol)
      .then((data) => { setOptionsRead(data); setOrStatus("done"); })
      .catch(() => setOrStatus("error"));
  }, [upperSymbol]);

  useEffect(() => {
    api.tickers.expectedMove(upperSymbol)
      .then((data) => {
        setExpectedMove(data);
        if (data.expiration_used) setSelectedExpiration(data.expiration_used);
        setEmStatus(data.expected_move_pct != null || data.current_price != null ? "done" : "empty");
      })
      .catch(() => setEmStatus("error"));
  }, [upperSymbol]);

  useEffect(() => {
    if (selectedExpiration === null) return;
    setOcStatus("loading");
    api.tickers.options(upperSymbol, selectedExpiration)
      .then((data) => {
        setOptionsChain(data);
        setOcStatus(data.calls.length > 0 || data.puts.length > 0 ? "done" : "empty");
      })
      .catch(() => setOcStatus("error"));
  }, [upperSymbol, selectedExpiration]);

  useEffect(() => {
    api.tickers.strategyData(upperSymbol)
      .then((d) => {
        setStrategyData(d);
        setSdStatus(d.strikes.length > 0 ? "done" : "empty");
      })
      .catch(() => setSdStatus("error"));
  }, [upperSymbol]);

  // ── Research note: initial load ──────────────────────────────────────────
  useEffect(() => {
    api.researchNotes
      .get(upperSymbol)
      .then((n) => { setNote(n); setNoteStatus("done"); })
      .catch((e: Error) => {
        if (e.message.startsWith("API 404")) { setNoteStatus("empty"); }
        else { setNoteStatus("error"); }
      });
  }, [upperSymbol]);

  // ── Research note: poll while generating/verifying ─────────────────────
  const pollInFlight = useRef(false);
  useEffect(() => {
    if (!note || (note.status !== "generating" && note.status !== "verifying")) return;
    const started = Date.now();
    const MAX_POLL_MS = 3 * 60 * 1000; // 3 minutes cap
    const id = setInterval(() => {
      if (pollInFlight.current) return;
      if (Date.now() - started > MAX_POLL_MS) { clearInterval(id); return; }
      pollInFlight.current = true;
      api.researchNotes
        .get(upperSymbol)
        .then((n) => { setNote(n); setNoteStatus("done"); })
        .catch(() => {})
        .finally(() => { pollInFlight.current = false; });
    }, 3000);
    return () => clearInterval(id);
  }, [note?.status, upperSymbol]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleGenerate() {
    try {
      const n = await api.researchNotes.generate(upperSymbol);
      setNote(n);
      setNoteStatus("done");
    } catch (e: unknown) {
      setNote((prev) =>
        prev
          ? { ...prev, status: "failed", error: e instanceof Error ? e.message : "Unknown error" }
          : null,
      );
    }
  }

  function handleRegenerate() {
    if (!window.confirm("Regenerate this research note? The current note will be replaced.")) return;
    void handleGenerate();
  }

  if (tickerStatus === "missing") notFound();

  if (tickerStatus === "loading") {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-4xl mx-auto animate-pulse space-y-4">
          <div className="h-4 bg-muted rounded w-16" />
          <div className="h-14 bg-muted rounded w-40 mt-6" />
          <div className="h-5 bg-muted rounded w-72" />
          <div className="h-20 bg-muted rounded w-full mt-8" />
          <div className="h-48 bg-muted rounded w-full" />
          <div className="h-64 bg-muted rounded w-full" />
        </div>
      </main>
    );
  }

  if (tickerStatus === "error") {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-4xl mx-auto">
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            Failed to load ticker: {tickerError}
          </div>
        </div>
      </main>
    );
  }

  if (!ticker) return null;

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          ← All tickers
        </Link>

        {/* Header */}
        <div className="mt-6 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-5xl font-bold tracking-tight">{ticker.symbol}</h1>
            {ticker.name && (
              <p className="text-xl text-muted-foreground mt-2">{ticker.name}</p>
            )}
          </div>
          <Link
            href={`/build?ticker=${ticker.symbol}`}
            className="shrink-0 self-center rounded-xl bg-primary text-primary-foreground px-5 py-2.5 text-sm font-semibold hover:bg-primary/90 transition-colors"
          >
            Build a trade on {ticker.symbol} →
          </Link>
        </div>

        {/* Live price header */}
        {quote && quote.price != null && (
          <div className="mt-5 flex items-center gap-5 flex-wrap">
            <div className="flex items-baseline gap-2.5">
              <span className="text-3xl font-bold tabular-nums tracking-tight">
                ${quote.price.toFixed(2)}
              </span>
              {chartStartPrice != null && (() => {
                const chg    = quote.price! - chartStartPrice;
                const chgPct = (chg / chartStartPrice) * 100;
                return (
                  <span className={cn(
                    "text-sm font-medium tabular-nums",
                    chg >= 0 ? "text-success" : "text-destructive",
                  )}>
                    {chg >= 0 ? "+" : ""}{chg.toFixed(2)}{" "}
                    ({chgPct >= 0 ? "+" : ""}{chgPct.toFixed(2)}%){" "}
                    <span className="font-normal opacity-60">{PERIOD_WINDOW_LABEL[chartPeriod]}</span>
                  </span>
                );
              })()}
            </div>
            {quote.high != null && quote.low != null && (
              <span className="text-xs text-muted-foreground ml-auto">
                H&nbsp;{quote.high.toFixed(2)} · L&nbsp;{quote.low.toFixed(2)}
              </span>
            )}
          </div>
        )}

        {/* Interactive price chart with earnings markers */}
        <PriceChart
          symbol={upperSymbol}
          period={chartPeriod}
          onPeriodChange={setChartPeriod}
          onChartLoad={handleChartLoad}
        />

        {/* Stats strip */}
        <div className="mt-8 flex flex-wrap gap-x-10 gap-y-4 rounded-lg border bg-card p-5">
          <Stat label="Sector"     value={ticker.sector} />
          <Stat label="Industry"   value={ticker.industry} />
          <Stat label="Exchange"   value={ticker.exchange} />
          <Stat label="Market Cap" value={ticker.market_cap != null ? formatMarketCap(ticker.market_cap) : null} />
        </div>

        {/* Upcoming Catalysts */}
        <div className="mt-10">
          <h2 className="text-lg font-semibold mb-4">
            Upcoming Catalysts
            {eventStatus === "done" && events.length > 0 && (
              <span className="ml-2 text-muted-foreground font-normal text-sm">({events.length})</span>
            )}
          </h2>

          {eventStatus === "loading" && (
            <div className="rounded-lg border bg-card p-5 space-y-5 animate-pulse">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex gap-4">
                  <div className="h-4 bg-muted rounded w-12 shrink-0 mt-0.5" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-muted rounded w-2/3" />
                    <div className="h-3 bg-muted rounded w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          )}
          {eventStatus === "error" && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              Failed to load events: {eventError}
            </div>
          )}
          {eventStatus === "done" && events.length === 0 && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center text-sm text-muted-foreground">
              No events in the next 60 days.
            </div>
          )}
          {eventStatus === "done" && events.length > 0 && (
            <div className="rounded-lg border bg-card px-5 divide-y divide-border">
              {events.map((event) => <CatalystRow key={event.id} event={event} />)}
            </div>
          )}
        </div>

        {/* Historical Reactions */}
        <div className="mt-10">
          <h2 className="text-lg font-semibold mb-4">
            Historical Reactions
            {reactionStatus === "done" && reactions.length > 0 && (
              <span className="ml-2 text-muted-foreground font-normal text-sm">({reactions.length})</span>
            )}
          </h2>

          {reactionStatus === "loading" && (
            <div className="rounded-lg border bg-card overflow-hidden animate-pulse">
              <div className="h-10 bg-muted/60 border-b" />
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="flex gap-4 px-3 py-3 border-b last:border-0">
                  <div className="h-4 bg-muted rounded w-16" />
                  <div className="h-4 bg-muted rounded w-14" />
                  <div className="h-4 bg-muted rounded w-16 ml-auto" />
                  <div className="h-4 bg-muted rounded w-14" />
                  <div className="h-4 bg-muted rounded w-14" />
                  <div className="h-4 bg-muted rounded w-14" />
                  <div className="h-4 bg-muted rounded w-16" />
                </div>
              ))}
            </div>
          )}
          {reactionStatus === "error" && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              Failed to load reactions: {reactionError}
            </div>
          )}
          {reactionStatus === "done" && reactions.length === 0 && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center text-sm text-muted-foreground">
              No reaction history available for this ticker yet.
            </div>
          )}
          {reactionStatus === "done" && reactions.length > 0 && (
            <>
              {reactionSummary && reactionSummary.total_quarters >= 3 && (
                <EarningsInsightsPanel s={reactionSummary} />
              )}
              <ReactionsTable reactions={reactions} />
            </>
          )}
        </div>

        {/* Research Note */}
        <div className="mt-10 mb-10">
          <h2 className="text-lg font-semibold mb-4">Research Note</h2>

          {/* Initial page load skeleton */}
          {noteStatus === "loading" && (
            <div className="rounded-lg border bg-card p-6 animate-pulse space-y-3">
              <div className="h-4 bg-muted rounded w-1/3" />
              <div className="h-4 bg-muted rounded w-full" />
              <div className="h-4 bg-muted rounded w-5/6" />
              <div className="h-4 bg-muted rounded w-2/3" />
            </div>
          )}

          {/* Fetch error (network / unexpected) */}
          {noteStatus === "error" && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center">
              <p className="text-sm text-muted-foreground mb-4">Could not load research note.</p>
              <button
                onClick={() => void handleGenerate()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Generate Research Note
              </button>
            </div>
          )}

          {/* No note yet — prompt to generate */}
          {noteStatus === "empty" && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center">
              <p className="text-sm font-medium mb-1">No research note generated yet.</p>
              <p className="text-xs text-muted-foreground mb-5">
                AI-generated summary using SEC filings + earnings history. Takes about 40 seconds.
              </p>
              <button
                onClick={() => void handleGenerate()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Generate Research Note
              </button>
            </div>
          )}

          {/* ── Live note states: generating → verifying → complete / failed ── */}
          {noteStatus === "done" && note && note.status === "generating" && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center animate-pulse">
              <p className="text-sm font-medium mb-1">Generating research note…</p>
              <p className="text-xs text-muted-foreground">
                Analyzing filings and earnings history · ~40 seconds
              </p>
            </div>
          )}

          {noteStatus === "done" && note && note.status === "verifying" && (
            <div className="rounded-lg border bg-card">
              {/* Ungrounded filing warning */}
              {note.source_filings.length === 0 && (
                <Callout severity="caution" banner>
                  <strong>Generated without SEC filing.</strong>{" "}
                  This note is based on general knowledge and earnings history only — not grounded in a current 10-Q or 10-K. Treat all claims with extra caution.
                </Callout>
              )}

              {/* Header bar */}
              <div className="flex items-center justify-between px-6 py-3 border-b text-xs text-muted-foreground">
                <span>
                  Generated {timeAgo(note.generated_at)}
                  {note.source_filings.length > 0 && (
                    <> · {note.source_filings[0].form_type} {note.source_filings[0].filing_date}</>
                  )}
                  {" · "}{note.input_tokens + note.output_tokens} tokens
                </span>
              </div>

              {/* Note content — structured or legacy markdown */}
              {note.structured_content ? (
                <StructuredNoteView
                  note={note.structured_content}
                  symbol={upperSymbol}
                  companyName={ticker?.name}
                  sector={ticker?.sector}
                  industry={ticker?.industry}
                />
              ) : (
                <div className="px-6 py-5 prose prose-sm dark:prose-invert max-w-none
                  prose-headings:text-foreground prose-headings:font-semibold
                  prose-p:text-foreground/90 prose-li:text-foreground/90
                  prose-strong:text-foreground">
                  <ReactMarkdown>{note.content}</ReactMarkdown>
                </div>
              )}

              {/* Verification in progress */}
              <div className="border-t px-6 py-3 flex items-center gap-2 text-xs text-muted-foreground">
                <span className="inline-block h-3 w-3 rounded-full border-2 border-muted-foreground/40 border-t-muted-foreground animate-spin" />
                Verifying claims against filings…
              </div>
            </div>
          )}

          {noteStatus === "done" && note && note.status === "failed" && (
            <div className="space-y-3">
              <Callout severity="caution" title="Generation failed">
                {note.error || "An unknown error occurred."}
              </Callout>
              <button
                onClick={() => void handleGenerate()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Try Again
              </button>
            </div>
          )}

          {noteStatus === "done" && note && note.status === "complete" && (
            <div className="rounded-lg border bg-card">
              {/* Ungrounded filing warning — shown when no SEC filing was available */}
              {note.source_filings.length === 0 && (
                <Callout severity="caution" banner>
                  <strong>Generated without SEC filing.</strong>{" "}
                  This note is based on general knowledge and earnings history only — not grounded in a current 10-Q or 10-K. Treat all claims with extra caution.
                </Callout>
              )}

              {/* Contradicted claims warning */}
              {note.verification && note.verification.summary.contradicted > 0 && (
                <Callout severity="alert" banner>
                  <strong>Verification found {note.verification.summary.contradicted} contradicted claim{note.verification.summary.contradicted !== 1 ? "s" : ""}.</strong>{" "}
                  See the verification section below for details. Consider regenerating.
                </Callout>
              )}

              {/* Header bar */}
              <div className="flex items-center justify-between px-6 py-3 border-b text-xs text-muted-foreground">
                <span>
                  Generated {timeAgo(note.generated_at)}
                  {note.source_filings.length > 0 && (
                    <> · {note.source_filings[0].form_type} {note.source_filings[0].filing_date}</>
                  )}
                  {" · "}{note.input_tokens + note.output_tokens} tokens
                </span>
                <button
                  onClick={handleRegenerate}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2"
                >
                  Regenerate
                </button>
              </div>

              {/* Note content — structured or legacy markdown */}
              {note.structured_content ? (
                <StructuredNoteView
                  note={note.structured_content}
                  symbol={upperSymbol}
                  companyName={ticker?.name}
                  sector={ticker?.sector}
                  industry={ticker?.industry}
                />
              ) : (
                <div className="px-6 py-5 prose prose-sm dark:prose-invert max-w-none
                  prose-headings:text-foreground prose-headings:font-semibold
                  prose-p:text-foreground/90 prose-li:text-foreground/90
                  prose-strong:text-foreground">
                  <ReactMarkdown>{note.content}</ReactMarkdown>
                </div>
              )}

              {/* Verification panel — or notice if verification was unavailable */}
              {note.verification ? (
                <VerificationPanel
                  verification={note.verification}
                  verifiedAt={note.verified_at}
                  model={note.verification_model}
                  open={verificationOpen}
                  onToggle={() => setVerificationOpen(o => !o)}
                />
              ) : (
                <div className="border-t px-6 py-3 text-xs text-muted-foreground">
                  Verification unavailable — claims in this note have not been checked against source data.
                  <button
                    onClick={() => {
                      void (async () => {
                        try {
                          const n = await api.researchNotes.verify(upperSymbol);
                          setNote(n);
                        } catch { /* ignore */ }
                      })();
                    }}
                    className="ml-2 underline underline-offset-2 hover:text-foreground transition-colors"
                  >
                    Retry verification
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Recent News ───────────────────────────────────────────────────── */}
        <div className="mt-10">
          <div className="mb-4">
            <h2 className="text-lg font-semibold">Recent News</h2>
            <p className="text-xs text-muted-foreground/60 mt-0.5">
              Live · from news sources · not verified
            </p>
          </div>

          {newsStatus === "loading" && (
            <div className="space-y-3 animate-pulse">
              {[0, 1, 2].map((i) => (
                <div key={i} className="rounded-lg border bg-card px-4 py-3 space-y-2">
                  <div className="h-4 bg-muted rounded w-3/4" />
                  <div className="h-3 bg-muted rounded w-1/2" />
                </div>
              ))}
            </div>
          )}
          {newsStatus === "empty" && (
            <p className="text-sm text-muted-foreground">No recent news in the last 48 hours.</p>
          )}
          {newsStatus === "error" && (
            <p className="text-sm text-muted-foreground">Couldn&apos;t load news right now.</p>
          )}
          {newsStatus === "done" && news && (() => {
            const visible = newsExpanded ? news.items : news.items.slice(0, 3);
            const hasMore = news.items.length > 3;
            return (
              <div className="space-y-2">
                {visible.map((item) => (
                  <div
                    key={item.datetime + item.headline.slice(0, 20)}
                    className="rounded-lg border border-border/60 bg-card px-4 py-3"
                  >
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-foreground hover:text-cool transition-colors leading-snug"
                    >
                      {item.headline}
                    </a>
                    <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground/70">
                      <span>{item.source}</span>
                      <span>·</span>
                      <span>{timeAgoUnix(item.datetime)}</span>
                    </div>
                    {item.summary && (
                      <p className="text-xs text-muted-foreground mt-1 line-clamp-2 leading-relaxed">
                        {item.summary}
                      </p>
                    )}
                  </div>
                ))}
                {hasMore && (
                  <button
                    type="button"
                    onClick={() => setNewsExpanded((o) => !o)}
                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors pt-1"
                  >
                    <span className="text-[10px]">{newsExpanded ? "▲" : "▼"}</span>
                    {newsExpanded
                      ? "Show less"
                      : `Show ${news.items.length - 3} more stories`}
                  </button>
                )}
              </div>
            );
          })()}
        </div>

        {/* ── Volatility Context ─────────────────────────────────────────────── */}
        <div className="mt-10">
          <h2 className="text-lg font-semibold mb-4">Volatility Context</h2>

          {rvStatus === "loading" && (
            <div className="rounded-lg border bg-card px-5 py-4 space-y-4 animate-pulse">
              <div className="flex justify-between">
                <div className="space-y-2">
                  <div className="h-3 bg-muted rounded w-36" />
                  <div className="h-8 bg-muted rounded w-24" />
                </div>
                <div className="space-y-2 text-right">
                  <div className="h-3 bg-muted rounded w-24 ml-auto" />
                  <div className="h-6 bg-muted rounded w-16 ml-auto" />
                </div>
              </div>
              <div className="h-2 bg-muted rounded-full" />
              <div className="grid grid-cols-3 gap-3">
                {[0,1,2].map(i => <div key={i} className="h-10 bg-muted rounded" />)}
              </div>
              <div className="h-3 bg-muted rounded w-3/4" />
            </div>
          )}
          {rvStatus === "error" && (
            <p className="text-sm text-muted-foreground">Could not load volatility data.</p>
          )}
          {rvStatus === "empty" && (
            <p className="text-sm text-muted-foreground">
              Insufficient price history for volatility analysis.
            </p>
          )}
          {rvStatus === "done" && realizedVol && (
            <RealizedVolPanel rv={realizedVol} />
          )}
        </div>

        {/* ── Options & Expected Move ────────────────────────────────────────── */}
        <div className="mt-10 mb-10">
          <h2 className="text-lg font-semibold mb-4">Options & Expected Move</h2>

          {/* AI options setup read */}
          {orStatus === "loading" && (
            <div className="rounded-lg border bg-card px-5 py-4 mb-6 animate-pulse space-y-2">
              <div className="h-3 bg-muted rounded w-40" />
              <div className="h-4 bg-muted rounded w-full" />
              <div className="h-4 bg-muted rounded w-11/12" />
              <div className="h-4 bg-muted rounded w-4/5" />
            </div>
          )}
          {orStatus === "done" && optionsRead && (
            <div className="rounded-lg border bg-card px-5 py-4 mb-6 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  AI read — options setup
                </span>
                <span className="text-[10px] text-muted-foreground/70">
                  · educational interpretation · not investment advice
                </span>
              </div>
              <p className="text-sm leading-relaxed text-foreground">{optionsRead.content}</p>
              <p className="text-[10px] text-muted-foreground/60">
                {optionsRead.model_used} · {optionsRead.cached ? "cached" : "generated"} {timeAgo(optionsRead.generated_at)}
              </p>
            </div>
          )}

          {emStatus === "loading" && (
            <div className="animate-pulse space-y-3">
              <div className="h-6 bg-muted rounded w-3/4 mb-4" />
              <div className="h-28 bg-muted rounded-lg" />
            </div>
          )}
          {emStatus === "error" && (
            <p className="text-sm text-muted-foreground">Could not load options data.</p>
          )}
          {emStatus === "empty" && (
            <p className="text-sm text-muted-foreground">No options data available for {upperSymbol}.</p>
          )}
          {emStatus === "done" && expectedMove && (
            <>
              {/* Plain-English summary — prominent, above the card */}
              {expectedMove.plain_summary && (
                <p className="text-base text-foreground leading-relaxed mb-4">
                  {expectedMove.plain_summary}
                </p>
              )}
              <ExpectedMoveCard
                em={expectedMove}
                onSelectExpiration={setSelectedExpiration}
              />
            </>
          )}

          {/* Education — rendered when both datasets are ready */}
          {emStatus === "done" && expectedMove && ocStatus === "done" && optionsChain && (
            <OptionsEducation
              em={expectedMove}
              chain={optionsChain}
              symbol={upperSymbol}
            />
          )}

          {/* Strategy explainer */}
          {sdStatus === "done" && strategyData && (
            <StrategyExplainer data={strategyData} symbol={upperSymbol} />
          )}
          {sdStatus === "empty" && (
            <p className="text-sm text-muted-foreground mt-4">
              Options strategy analysis unavailable for {upperSymbol}.
            </p>
          )}
        </div>

      </div>
    </main>
  );
}