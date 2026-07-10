"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, notFound } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from "recharts";
import {
  api, type Ticker, type TickerQuote, type TickerChart, type EarningsMarker,
  type Event, type EventType, type EarningsOutcome, type HistoricalReaction,
  type ReactionSummary, type ResearchNote, type VerificationClaim, type VerificationResult,
  type OptionsRead, type RealizedVol, type ExpectedMove, type OptionsChain,
  type StrategyData, type StrikeData, type NewsResponse, type OptionsBundle,
} from "@/lib/api";
import { cn, rvRankShort } from "@/lib/utils";
import Callout from "@/components/Callout";
import StructuredNoteView from "@/components/StructuredNoteView";
import Tip from "@/components/Tip";

// Extracted components
import ExpectedMoveCard from "@/components/ticker/ExpectedMoveCard";
import ExplainTip from "@/components/ticker/ExplainTip";
import OptionsEducation from "@/components/ticker/OptionsEducation";
import StrategyExplainer from "@/components/ticker/StrategyExplainer";
import RealizedVolPanel from "@/components/ticker/RealizedVolPanel";

// ── Date / number helpers ─────────────────────────────────────────────────────

const TODAY = (() => {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
})();
const CURRENT_YEAR = TODAY.getFullYear();

function formatMarketCap(n: number): string {
  if (n >= 1_000_000_000_000) return `$${(n / 1_000_000_000_000).toFixed(1)}T`;
  if (n >= 1_000_000_000)     return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)         return `$${(n / 1_000_000).toFixed(0)}M`;
  return `$${n.toLocaleString("en-US")}`;
}

function formatEventDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const mon = d.toLocaleString("en-US", { month: "short" });
  const day = d.getDate();
  return d.getFullYear() === CURRENT_YEAR ? `${mon} ${day}` : `${mon} ${day}, ${d.getFullYear()}`;
}

function daysFromToday(iso: string): number {
  const d = new Date(iso + "T00:00:00");
  return Math.round((d.getTime() - TODAY.getTime()) / 86_400_000);
}

function formatPrice(v: string | null): string {
  if (v == null) return "—";
  const n = parseFloat(v);
  return isNaN(n) ? "—" : `$${n.toFixed(2)}`;
}

function formatVolume(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`;
  if (v >= 1_000_000)     return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000)         return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1)  return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function timeAgoUnix(secs: number): string {
  return timeAgo(new Date(secs * 1000).toISOString());
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

function EarningsInsightsPanel({ s, symbol }: { s: ReactionSummary; symbol: string }) {
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
      <div>
        <p className="text-sm font-semibold">
          <ExplainTip term="beat" metric="beat_drop_pattern" symbol={symbol}>Beat EPS</ExplainTip> in {s.beat_count} of {s.total_quarters} quarter{s.total_quarters !== 1 ? "s" : ""}{" "}
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

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-2">
        {(
          [
            ["Avg next-day move on beats", s.avg_1d_on_beat],
            ["Avg next-day move on misses", s.avg_1d_on_miss],
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
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Avg move size (any direction)</p>
          <p className="text-sm font-semibold tabular-nums text-foreground">
            {s.avg_abs_1d != null ? `±${s.avg_abs_1d.toFixed(2)}%` : "—"}
          </p>
        </div>

        {s.sector_avg_abs_1d != null && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium">
              {s.sector ?? "Sector"} avg move size
            </p>
            <p className="text-sm font-semibold tabular-nums text-muted-foreground">
              ±{s.sector_avg_abs_1d.toFixed(2)}%
            </p>
          </div>
        )}
      </div>

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

// ── Revenue outcome helper ────────────────────────────────────────────────────

function revenueOutcome(r: HistoricalReaction): { label: string; cls: string } | null {
  if (r.revenue_actual == null || r.revenue_estimate == null) return null;
  const ratio = r.revenue_actual / r.revenue_estimate;
  if (ratio > 1.005) return { label: "Beat", cls: "text-green-700 dark:text-green-400" };
  if (ratio < 0.995) return { label: "Miss", cls: "text-red-600 dark:text-red-400" };
  return { label: "Inline", cls: "text-muted-foreground" };
}

// ── Reactions table (updated headers + revenue column) ────────────────────────

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

  const hasRevenue = reactions.some((r) => r.revenue_actual != null && r.revenue_estimate != null);

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

      <DistributionPanel rows={filtered} filter={outcomeFilter} />

      <div className="rounded-lg border bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <SortTh label="Date"    col="event_date"    sort={sort} onSort={handleSort} align="left" />
                <th className="px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    Outcome
                    <span
                      title="Beat/miss/meet refers to EPS surprise vs. analyst estimate. Stock direction is shown separately by the arrow next to the badge and the 1d/3d/5d columns."
                      className="cursor-help opacity-60 hover:opacity-100 transition-opacity"
                    >
                      ⓘ
                    </span>
                  </span>
                </th>
                {hasRevenue && (
                  <th className="px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Revenue
                  </th>
                )}
                <th className="px-3 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Close Before
                </th>
                <th className="px-3 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Close After
                </th>
                <SortTh label="1-Day"  col="pct_change_1d" sort={sort} onSort={handleSort} />
                <SortTh label="3-Day"  col="pct_change_3d" sort={sort} onSort={handleSort} />
                <SortTh label="5-Day"  col="pct_change_5d" sort={sort} onSort={handleSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sorted.map((r) => {
                const rev = revenueOutcome(r);
                return (
                  <tr key={r.id} className="hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-2.5 text-sm tabular-nums text-muted-foreground whitespace-nowrap">
                      {formatEventDate(r.event_date)}
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
                    {hasRevenue && (
                      <td className="px-3 py-2.5 text-sm">
                        {rev ? (
                          <span className={cn("text-xs font-medium", rev.cls)}>{rev.label}</span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    )}
                    <td className="px-3 py-2.5 text-right text-sm tabular-nums">
                      {formatPrice(r.close_before)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-sm tabular-nums">
                      {formatPrice(r.close_after)}
                    </td>
                    <PctCell value={r.pct_change_1d} />
                    <PctCell value={r.pct_change_3d} />
                    <PctCell value={r.pct_change_5d} />
                  </tr>
                );
              })}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={hasRevenue ? 8 : 7} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    No rows match the selected filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="px-3 py-2 text-xs text-muted-foreground border-t bg-muted/20">
          Moves measured from event-day close. Days are calendar days, rolling forward to next
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

// ── Source filings row ─────────────────────────────────────────────────────────

function SourceFilingsRow({ filings }: { filings: ResearchNote["source_filings"] }) {
  if (!filings || filings.length === 0) return null;
  return (
    <div className="border-t px-6 py-3">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium mb-1.5">Sources</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {filings.map((f, i) => (
          <a
            key={i}
            href={f.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2"
          >
            {f.form_type} · {f.filing_date}
          </a>
        ))}
      </div>
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

function formatTooltipDate(date: string, period: ChartPeriod): string {
  if (date.length > 10) {
    const d = new Date(date);
    return d.toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit", timeZoneName: "short",
    });
  }
  return date;
}

const OUTCOME_DOT_COLOR: Record<string, string> = {
  beat: "#22c55e",
  miss: "#ef4444",
  meet: "#9ca3af",
  unknown: "#9ca3af",
};

function PriceChartTooltip({
  active,
  payload,
  period,
  earningsMap,
}: {
  active?: boolean;
  payload?: Array<{ payload: { date?: string; epochMs?: number; close: number } }>;
  period: ChartPeriod;
  earningsMap: Map<string, EarningsMarker>;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const dateStr = p.date ?? (p.epochMs != null ? new Date(p.epochMs).toISOString().slice(0, 10) : "");
  const marker = earningsMap.get(dateStr);
  return (
    <div className="rounded border bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 shadow px-3 py-2 text-xs space-y-0.5">
      <p className="text-zinc-500 dark:text-zinc-400">{formatTooltipDate(dateStr, period)}</p>
      <p className="font-semibold text-zinc-900 dark:text-zinc-100 text-sm">${p.close.toFixed(2)}</p>
      {marker && (
        <div className="border-t border-zinc-200 dark:border-zinc-700 pt-1 mt-1 space-y-0.5">
          <p style={{ color: OUTCOME_DOT_COLOR[marker.outcome] }} className="font-medium capitalize">
            {marker.outcome === "unknown" ? "Earnings" : `Earnings ${marker.outcome}`}
          </p>
          {marker.eps_estimate != null && marker.eps_actual != null && (
            <p className="text-zinc-500 dark:text-zinc-400">
              EPS: {marker.eps_actual.toFixed(2)} vs {marker.eps_estimate.toFixed(2)} est.
            </p>
          )}
          {marker.pct_change_1d != null && (
            <p className={cn(
              "font-medium",
              marker.pct_change_1d > 0 ? "text-green-600 dark:text-green-400" : marker.pct_change_1d < 0 ? "text-red-500 dark:text-red-400" : "text-zinc-500",
            )}>
              T+1: {marker.pct_change_1d > 0 ? "+" : ""}{marker.pct_change_1d.toFixed(2)}%
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
  impliedRangeLow,
  impliedRangeHigh,
}: {
  symbol: string;
  period: ChartPeriod;
  onPeriodChange: (p: ChartPeriod) => void;
  onChartLoad: (startPrice: number | null) => void;
  impliedRangeLow?: number | null;
  impliedRangeHigh?: number | null;
}) {
  const [chartData, setChartData] = useState<TickerChart | null>(null);

  useEffect(() => {
    setChartData(null);
    api.tickers
      .chart(symbol, period)
      .then((data) => {
        setChartData(data);
        onChartLoad(data.start_price);
      })
      .catch(() => setChartData(null));
  }, [symbol, period]); // eslint-disable-line react-hooks/exhaustive-deps

  const earningsMap = useMemo(() => {
    const m = new Map<string, EarningsMarker>();
    if (chartData) {
      for (const mk of chartData.earnings_markers) m.set(mk.date, mk);
    }
    return m;
  }, [chartData]);

  const isIntraday = period === "1d" || period === "7d";

  const lineData = useMemo(() => {
    if (!chartData) return [];
    return chartData.history.map((p, i) => ({
      ...p,
      epochMs: new Date(p.date).getTime(),
      idx: i,
    }));
  }, [chartData]);

  const yDomain = useMemo<[number, number]>(() => {
    if (lineData.length === 0) return [0, 1];
    const closes = lineData.map((d) => d.close);
    const mn = Math.min(...closes);
    const mx = Math.max(...closes);
    const pad = (mx - mn) * 0.05 || mx * 0.01;
    return [mn - pad, mx + pad];
  }, [lineData]);

  if (!chartData || lineData.length === 0) {
    return (
      <div className="mt-6 rounded-lg border bg-card px-4 py-20 text-center text-sm text-muted-foreground animate-pulse">
        Loading chart…
      </div>
    );
  }

  const earningsMarkers = chartData.earnings_markers.filter((mk) => {
    if (isIntraday) return false;
    return lineData.some((d) => d.date === mk.date);
  });

  const startPrice = chartData.start_price;

  return (
    <div className="mt-6">
      {/* Period selector */}
      <div className="flex gap-1 mb-3">
        {CHART_PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => onPeriodChange(p)}
            className={cn(
              "px-2 py-1 rounded text-xs font-medium transition-colors",
              p === period
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="rounded-lg border bg-card px-2 py-3">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart
            data={lineData}
            margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey={isIntraday ? "idx" : "epochMs"}
              type={isIntraday ? "category" : "number"}
              domain={isIntraday ? undefined : ["dataMin", "dataMax"]}
              tickFormatter={(val) => {
                if (isIntraday) {
                  const pt = lineData[val as number];
                  if (!pt) return "";
                  if (period === "1d") {
                    const d = new Date(pt.date);
                    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
                  }
                  return pt.date.slice(5, 10);
                }
                return new Date(val as number).toLocaleDateString("en-US", { month: "short", day: "numeric" });
              }}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              axisLine={false}
              tickLine={false}
              minTickGap={40}
            />
            <YAxis
              domain={yDomain}
              tickFormatter={(v) => `$${v.toFixed(0)}`}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              axisLine={false}
              tickLine={false}
              width={50}
            />
            <Tooltip
              content={
                <PriceChartTooltip period={period} earningsMap={earningsMap} />
              }
            />
            {/* Start-of-period reference */}
            {startPrice != null && (
              <ReferenceLine
                y={startPrice}
                stroke="hsl(var(--muted-foreground))"
                strokeDasharray="4 4"
                strokeOpacity={0.4}
              />
            )}
            {/* Implied range shading */}
            {impliedRangeLow != null && impliedRangeHigh != null && (
              <ReferenceArea
                y1={impliedRangeLow}
                y2={impliedRangeHigh}
                fill="hsl(var(--primary))"
                fillOpacity={0.06}
                stroke="hsl(var(--primary))"
                strokeOpacity={0.15}
                strokeDasharray="4 4"
              />
            )}
            {/* Earnings markers */}
            {earningsMarkers.map((mk) => {
              const color = OUTCOME_DOT_COLOR[mk.outcome] ?? OUTCOME_DOT_COLOR.unknown;
              return (
                <ReferenceLine
                  key={mk.date}
                  x={new Date(mk.date).getTime()}
                  stroke={color}
                  strokeOpacity={0.5}
                  strokeDasharray="3 3"
                />
              );
            })}
            <Line
              type="monotone"
              dataKey="close"
              stroke="hsl(var(--foreground))"
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
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

// ── Section nav ──────────────────────────────────────────────────────────────

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "catalysts", label: "Catalysts" },
  { id: "history", label: "History" },
  { id: "market-view", label: "Options" },
  { id: "research", label: "Research" },
] as const;

function SectionNav() {
  const [active, setActive] = useState("overview");

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the topmost intersecting section (lowest boundingClientRect.top)
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive((prev) => {
              // Find all currently-intersecting sections and pick the one closest to top
              const ids = SECTIONS.map((s) => s.id);
              const topmost = ids.reduce<{ id: string; top: number } | null>((best, id) => {
                const el = document.getElementById(id);
                if (!el) return best;
                const rect = el.getBoundingClientRect();
                // Section top is within (or above) viewport and bottom is below header+nav (~96px)
                if (rect.bottom > 96 && (!best || rect.top < best.top)) {
                  return { id, top: rect.top };
                }
                return best;
              }, null);
              return topmost ? topmost.id : prev;
            });
          }
        }
      },
      // 96px = site header (52px) + section nav (~44px)
      { rootMargin: "-96px 0px -60% 0px", threshold: 0 },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav className="sticky top-13 z-30 bg-background/95 backdrop-blur border-b -mx-8 px-8 mb-8">
      <div className="max-w-4xl mx-auto flex gap-1 overflow-x-auto py-2">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            onClick={(e) => {
              e.preventDefault();
              document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className={cn(
              "px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors",
              active === s.id
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground hover:bg-muted",
            )}
          >
            {s.label}
          </a>
        ))}
      </div>
    </nav>
  );
}

// ── "Why now" strip ──────────────────────────────────────────────────────────

function WhyNowStrip({
  events,
  realizedVol,
}: {
  events: Event[];
  realizedVol: RealizedVol | null;
}) {
  const chips: { label: string; cls: string }[] = [];

  // Reporting soon?
  const nextEarnings = events.find((e) => e.event_type === "earnings");
  if (nextEarnings) {
    const days = daysFromToday(nextEarnings.event_date);
    if (days >= 0 && days <= 7) {
      chips.push({
        label: days === 0 ? "Reports today" : days === 1 ? "Reports tomorrow" : `Reports in ${days}d`,
        cls: "bg-cool/10 text-cool",
      });
    }
  }

  // Unusually active vol?
  if (realizedVol?.rv_rank != null && realizedVol.rv_rank >= 85) {
    const tier = realizedVol.rv_rank >= 90 ? "extreme" : "elevated";
    chips.push({
      label: `Volatility: ${tier} vs own history`,
      cls: tier === "extreme" ? "bg-primary/10 text-primary" : "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    });
  }

  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {chips.map((c, i) => (
        <span key={i} className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium", c.cls)}>
          {c.label}
        </span>
      ))}
    </div>
  );
}

// ── Metrics row (IV/RV spread + put/call ratio) ──────────────────────────────

function MetricsRow({
  optionsRead,
  optionsChain,
  symbol,
}: {
  optionsRead: OptionsRead | null;
  optionsChain: OptionsChain | null;
  symbol: string;
}) {
  const spread = optionsRead?.iv_rv_spread_pp;

  const pcRatio = useMemo(() => {
    if (!optionsChain) return null;
    const putVol = optionsChain.puts.reduce((s, p) => s + (p.volume ?? 0), 0);
    const callVol = optionsChain.calls.reduce((s, c) => s + (c.volume ?? 0), 0);
    if (callVol === 0) return null;
    return putVol / callVol;
  }, [optionsChain]);

  if (spread == null && pcRatio == null) return null;

  const spreadLabel =
    spread == null ? null
    : spread > 10 ? "options rich vs realized"
    : spread < -10 ? "options cheap vs realized"
    : "in line";

  const spreadColor =
    spread == null ? ""
    : spread > 10 ? "text-amber-600 dark:text-amber-400"
    : spread < -10 ? "text-green-700 dark:text-green-400"
    : "text-muted-foreground";

  return (
    <div className="grid grid-cols-2 gap-4 mb-6">
      {spread != null && (
        <div className="rounded-lg border bg-card px-4 py-3">
          <p className="text-xs text-muted-foreground mb-0.5">
            <ExplainTip term="iv/rv spread" metric="iv_rv_spread" symbol={symbol}>IV − RV Spread</ExplainTip>
          </p>
          <p className="text-lg font-bold tabular-nums">
            {spread > 0 ? "+" : ""}{spread.toFixed(1)}pp
          </p>
          {spreadLabel && (
            <p className={cn("text-xs font-medium mt-0.5", spreadColor)}>{spreadLabel}</p>
          )}
        </div>
      )}
      {pcRatio != null && (
        <div className="rounded-lg border bg-card px-4 py-3">
          <p className="text-xs text-muted-foreground mb-0.5">
            <ExplainTip term="put/call ratio" metric="put_call" symbol={symbol}>Put/Call Ratio</ExplainTip>
          </p>
          <p className="text-lg font-bold tabular-nums">{pcRatio.toFixed(2)}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {pcRatio > 1.2 ? "put-heavy" : pcRatio < 0.7 ? "call-heavy" : "balanced"}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type TickerStatus = "loading" | "found" | "missing" | "error";
type SectionStatus = "loading" | "done" | "error";

export default function TickerPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const upperSymbol = symbol.toUpperCase();

  const [ticker, setTicker]             = useState<Ticker | null>(null);
  const [tickerStatus, setTickerStatus] = useState<TickerStatus>("loading");
  const [tickerError, setTickerError]   = useState<string | null>(null);

  const [events, setEvents]             = useState<Event[]>([]);
  const [eventStatus, setEventStatus]   = useState<SectionStatus>("loading");
  const [eventError, setEventError]     = useState<string | null>(null);

  const [reactions, setReactions]             = useState<HistoricalReaction[]>([]);
  const [reactionStatus, setReactionStatus]   = useState<SectionStatus>("loading");
  const [reactionError, setReactionError]     = useState<string | null>(null);
  const [reactionSummary, setReactionSummary] = useState<ReactionSummary | null>(null);

  const [quote, setQuote]               = useState<TickerQuote | null>(null);
  const [chartPeriod, setChartPeriod]   = useState<ChartPeriod>("1y");
  const [chartStartPrice, setChartStartPrice] = useState<number | null>(null);
  const handleChartLoad = useCallback((startPrice: number | null) => {
    setChartStartPrice(startPrice);
  }, []);

  const [realizedVol, setRealizedVol]     = useState<RealizedVol | null>(null);
  const [rvStatus, setRvStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");
  const [optionsRead, setOptionsRead]     = useState<OptionsRead | null>(null);
  const [orStatus, setOrStatus]           = useState<"loading" | "done" | "error">("loading");

  // Options bundle replaces 3 separate calls
  const [expectedMove, setExpectedMove]     = useState<ExpectedMove | null>(null);
  const [optionsChain, setOptionsChain]     = useState<OptionsChain | null>(null);
  const [strategyData, setStrategyData]     = useState<StrategyData | null>(null);
  const [strikesFallback, setStrikesFallback] = useState(false);
  const [bundleStatus, setBundleStatus]     = useState<"loading" | "done" | "empty" | "error">("loading");
  const [selectedExpiration, setSelectedExpiration] = useState<string | null>(null);

  const [note, setNote]               = useState<ResearchNote | null>(null);
  const [noteStatus, setNoteStatus]   = useState<"loading" | "empty" | "done" | "error">("loading");
  const [verificationOpen, setVerificationOpen] = useState(false);

  const [news, setNews]               = useState<NewsResponse | null>(null);
  const [newsStatus, setNewsStatus]   = useState<"loading" | "done" | "empty" | "error">("loading");
  const [newsExpanded, setNewsExpanded] = useState(false);

  // ── Data fetching ──────────────────────────────────────────────────────────

  // Single-ticker lookup (replaces fetch-all-tickers)
  useEffect(() => {
    api.tickers
      .bySymbol(upperSymbol)
      .then((t) => { setTicker(t); setTickerStatus("found"); })
      .catch((e: Error) => {
        if (e.message.includes("404")) { setTickerStatus("missing"); }
        else { setTickerError(e.message); setTickerStatus("error"); }
      });
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

  // Options bundle: single request replaces expected-move + strategy-data + chain
  useEffect(() => {
    api.tickers.optionsBundle(upperSymbol)
      .then((bundle: OptionsBundle) => {
        setExpectedMove(bundle.expected_move);
        // Derive strikes from chain when backend returns empty strikes
        const sd = bundle.strategy_data;
        let isFallback = false;
        if (sd.strikes.length === 0 && bundle.chain) {
          isFallback = true;
          const spot = bundle.chain.current_price ?? bundle.expected_move.current_price;
          const strikeMap = new Map<number, StrikeData>();
          for (const c of bundle.chain.calls) {
            // Skip contracts with no usable price or >25% from spot
            const hasMid = c.bid != null && c.ask != null && c.bid + c.ask > 0;
            const price = hasMid ? (c.bid! + c.ask!) / 2 : c.last_price;
            if (price == null || price <= 0) continue;
            if (spot != null && Math.abs(c.strike - spot) / spot > 0.25) continue;
            strikeMap.set(c.strike, {
              strike: c.strike, call_mid: price, put_mid: null,
              call_iv: c.implied_volatility, put_iv: null, is_atm: c.is_atm,
            });
          }
          for (const p of bundle.chain.puts) {
            const hasMid = p.bid != null && p.ask != null && p.bid + p.ask > 0;
            const price = hasMid ? (p.bid! + p.ask!) / 2 : p.last_price;
            if (price == null || price <= 0) continue;
            if (spot != null && Math.abs(p.strike - spot) / spot > 0.25) continue;
            const existing = strikeMap.get(p.strike);
            if (existing) {
              existing.put_mid = price;
              existing.put_iv = p.implied_volatility;
            } else {
              strikeMap.set(p.strike, {
                strike: p.strike, call_mid: null, put_mid: price,
                call_iv: null, put_iv: p.implied_volatility, is_atm: p.is_atm,
              });
            }
          }
          sd.strikes = Array.from(strikeMap.values()).sort((a, b) => a.strike - b.strike);
        }
        setStrikesFallback(isFallback);
        setStrategyData(sd);
        setOptionsChain(bundle.chain);
        if (bundle.expected_move.expiration_used) {
          setSelectedExpiration(bundle.expected_move.expiration_used);
        }
        setBundleStatus(
          bundle.expected_move.expected_move_pct != null || bundle.expected_move.current_price != null
            ? "done" : "empty"
        );
      })
      .catch(() => setBundleStatus("error"));
  }, [upperSymbol]);

  // Chain re-fetch when user changes expiration (separate from bundle)
  const bundleExpiration = expectedMove?.expiration_used ?? null;
  useEffect(() => {
    if (selectedExpiration === null || selectedExpiration === bundleExpiration) return;
    api.tickers.options(upperSymbol, selectedExpiration)
      .then((data) => setOptionsChain(data))
      .catch(() => {});
  }, [upperSymbol, selectedExpiration, bundleExpiration]);

  // Research note: initial load
  useEffect(() => {
    api.researchNotes
      .get(upperSymbol)
      .then((n) => { setNote(n); setNoteStatus("done"); })
      .catch((e: Error) => {
        if (e.message.startsWith("API 404")) { setNoteStatus("empty"); }
        else { setNoteStatus("error"); }
      });
  }, [upperSymbol]);

  // Research note: poll while generating/verifying
  const pollInFlight = useRef(false);
  useEffect(() => {
    if (!note || (note.status !== "generating" && note.status !== "verifying")) return;
    const started = Date.now();
    const MAX_POLL_MS = 3 * 60 * 1000;
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

        {/* ── OVERVIEW ────────────────────────────────────────────────── */}
        <section id="overview">
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

          {/* "Why now" strip */}
          <WhyNowStrip events={events} realizedVol={realizedVol} />

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

          {/* Interactive price chart with implied range overlay */}
          <PriceChart
            symbol={upperSymbol}
            period={chartPeriod}
            onPeriodChange={setChartPeriod}
            onChartLoad={handleChartLoad}
            impliedRangeLow={expectedMove?.implied_range_low}
            impliedRangeHigh={expectedMove?.implied_range_high}
          />

          {/* Stats strip */}
          <div className="mt-8 flex flex-wrap gap-x-10 gap-y-4 rounded-lg border bg-card p-5">
            <Stat label="Sector"     value={ticker.sector} />
            <Stat label="Industry"   value={ticker.industry} />
            <Stat label="Exchange"   value={ticker.exchange} />
            <Stat label="Market Cap" value={ticker.market_cap != null ? formatMarketCap(ticker.market_cap) : null} />
          </div>
        </section>

        {/* Section nav */}
        <SectionNav />

        {/* ── CATALYSTS ───────────────────────────────────────────────── */}
        <section id="catalysts" className="scroll-mt-28">
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
        </section>

        {/* ── HISTORY ─────────────────────────────────────────────────── */}
        <section id="history" className="mt-10 scroll-mt-28">
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
                <EarningsInsightsPanel s={reactionSummary} symbol={upperSymbol} />
              )}
              <ReactionsTable reactions={reactions} />
            </>
          )}
        </section>

        {/* ── MARKET VIEW (RV → Metrics → Expected Move → Options Read → Education → Strategies) ── */}
        <section id="market-view" className="mt-10 mb-10 scroll-mt-28">
          <h2 className="text-lg font-semibold mb-4">Market View</h2>

          {/* Realized Volatility */}
          {rvStatus === "loading" && (
            <div className="rounded-lg border bg-card px-5 py-4 space-y-4 animate-pulse mb-6">
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
            <p className="text-sm text-muted-foreground mb-6">Could not load volatility data.</p>
          )}
          {rvStatus === "empty" && (
            <p className="text-sm text-muted-foreground mb-6">
              Insufficient price history for volatility analysis.
            </p>
          )}
          {rvStatus === "done" && realizedVol && (
            <div className="mb-6">
              <RealizedVolPanel rv={realizedVol} symbol={upperSymbol} />
            </div>
          )}

          {/* Metrics row: IV/RV spread + put/call ratio */}
          <MetricsRow optionsRead={optionsRead} optionsChain={optionsChain} symbol={upperSymbol} />

          {/* Expected Move */}
          {bundleStatus === "loading" && (
            <div className="animate-pulse space-y-3 mb-6">
              <div className="h-6 bg-muted rounded w-3/4 mb-4" />
              <div className="h-28 bg-muted rounded-lg" />
            </div>
          )}
          {bundleStatus === "error" && (
            <p className="text-sm text-muted-foreground mb-6">Could not load options data.</p>
          )}
          {bundleStatus === "empty" && (
            <p className="text-sm text-muted-foreground mb-6">No options data available for {upperSymbol}.</p>
          )}
          {bundleStatus === "done" && expectedMove && (
            <div className="mb-6">
              {expectedMove.plain_summary && (
                <p className="text-base text-foreground leading-relaxed mb-4">
                  {expectedMove.plain_summary}
                </p>
              )}
              <ExpectedMoveCard
                em={expectedMove}
                symbol={upperSymbol}
                onSelectExpiration={setSelectedExpiration}
              />
            </div>
          )}

          {/* AI options read */}
          {orStatus === "loading" && (
            <div className="rounded-lg border bg-card px-5 py-4 mb-6 animate-pulse space-y-2">
              <div className="h-3 bg-muted rounded w-40" />
              <div className="h-4 bg-muted rounded w-full" />
              <div className="h-4 bg-muted rounded w-11/12" />
              <div className="h-4 bg-muted rounded w-4/5" />
            </div>
          )}
          {orStatus === "done" && optionsRead && optionsRead.model_used !== "none" && (
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

          {/* Options Education */}
          {bundleStatus === "done" && expectedMove && optionsChain && (
            <OptionsEducation
              em={expectedMove}
              chain={optionsChain}
              symbol={upperSymbol}
            />
          )}

          {/* Strategy explainer */}
          {bundleStatus === "done" && strategyData && strategyData.strikes.length > 0 && strikesFallback && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-4 mb-1 italic">
              Prices from last trade — live quotes unavailable (market closed or thin). Treat P&L figures as approximate.
            </p>
          )}
          {bundleStatus === "done" && strategyData && strategyData.strikes.length > 0 && (
            <StrategyExplainer data={strategyData} symbol={upperSymbol} />
          )}
          {bundleStatus === "done" && strategyData && strategyData.strikes.length === 0 && (
            <p className="text-sm text-muted-foreground mt-4">
              Options strategy analysis unavailable for {upperSymbol}.
            </p>
          )}
        </section>

        {/* ── RESEARCH NOTE ───────────────────────────────────────────── */}
        <section id="research" className="mt-10 mb-10 scroll-mt-28">
          <h2 className="text-lg font-semibold mb-4">Research Note</h2>

          {noteStatus === "loading" && (
            <div className="rounded-lg border bg-card p-6 animate-pulse space-y-3">
              <div className="h-4 bg-muted rounded w-1/3" />
              <div className="h-4 bg-muted rounded w-full" />
              <div className="h-4 bg-muted rounded w-5/6" />
              <div className="h-4 bg-muted rounded w-2/3" />
            </div>
          )}

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
              {note.source_filings.length === 0 && (
                <Callout severity="caution" banner>
                  <strong>Generated without SEC filing.</strong>{" "}
                  This note is based on general knowledge and earnings history only — not grounded in a current 10-Q or 10-K. Treat all claims with extra caution.
                </Callout>
              )}
              <div className="flex items-center justify-between px-6 py-3 border-b text-xs text-muted-foreground">
                <span>
                  Generated {timeAgo(note.generated_at)}
                  {note.source_filings.length > 0 && (
                    <> · {note.source_filings[0].form_type} {note.source_filings[0].filing_date}</>
                  )}
                  {" · "}{note.input_tokens + note.output_tokens} tokens
                </span>
              </div>
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
              {note.source_filings.length === 0 && (
                <Callout severity="caution" banner>
                  <strong>Generated without SEC filing.</strong>{" "}
                  This note is based on general knowledge and earnings history only — not grounded in a current 10-Q or 10-K. Treat all claims with extra caution.
                </Callout>
              )}
              {note.verification && note.verification.summary.contradicted > 0 && (
                <Callout severity="alert" banner>
                  <strong>Verification found {note.verification.summary.contradicted} contradicted claim{note.verification.summary.contradicted !== 1 ? "s" : ""}.</strong>{" "}
                  See the verification section below for details. Consider regenerating.
                </Callout>
              )}
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
              {note.verification ? (
                <>
                  <VerificationPanel
                    verification={note.verification}
                    verifiedAt={note.verified_at}
                    model={note.verification_model}
                    open={verificationOpen}
                    onToggle={() => setVerificationOpen(o => !o)}
                  />
                  <SourceFilingsRow filings={note.source_filings} />
                </>
              ) : (
                <>
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
                  <SourceFilingsRow filings={note.source_filings} />
                </>
              )}
            </div>
          )}
        </section>

        {/* ── NEWS ────────────────────────────────────────────────────── */}
        <div className="mt-10 mb-10">
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

      </div>
    </main>
  );
}
