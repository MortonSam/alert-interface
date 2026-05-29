"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useParams, notFound } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api, type Ticker, type TickerQuote, type TickerChart, type EarningsMarker, type Event, type EventType, type EarningsOutcome, type HistoricalReaction, type ResearchNote, type VerificationClaim, type VerificationResult, type ExpectedMove, type OptionsChain, type OptionContract } from "@/lib/api";
import { cn } from "@/lib/utils";

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

// ── Catalyst section helpers ──────────────────────────────────────────────────

const EVENT_STYLES: Record<EventType, { label: string; cls: string }> = {
  earnings:       { label: "Earnings",       cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300" },
  macro:          { label: "Macro",          cls: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300" },
  fda:            { label: "FDA",            cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
  ex_dividend:    { label: "Ex-Div",         cls: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300" },
  product_launch: { label: "Launch",         cls: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300" },
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
  beat:    { label: "Beat",    cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
  miss:    { label: "Miss",    cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
  meet:    { label: "Meet",    cls: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300" },
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
    days <= 7   ? "bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-300"
    : days <= 30 ? "bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-300"
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
                ? key === "beat" ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                  : key === "miss" ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                  : key === "meet" ? "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200"
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
                    <span className="inline-flex items-center gap-1">
                      <OutcomeBadge outcome={r.outcome} />
                      {r.pct_change_1d == null ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : parseFloat(r.pct_change_1d) > 0 ? (
                        <span className="text-xs font-medium text-green-600 dark:text-green-400">↑</span>
                      ) : (
                        <span className="text-xs font-medium text-red-500 dark:text-red-400">↓</span>
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
  supported:    { dot: "bg-green-500",  badge: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",  label: "Supported" },
  unsupported:  { dot: "bg-amber-400",  badge: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",  label: "Unsupported" },
  contradicted: { dot: "bg-red-500",    badge: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",          label: "Contradicted" },
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

const CHART_PERIODS = ["1mo", "3mo", "6mo", "1y", "5y"] as const;
type ChartPeriod = (typeof CHART_PERIODS)[number];

const PERIOD_LABELS: Record<ChartPeriod, string> = {
  "1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1Y", "5y": "5Y",
};

const OUTCOME_DOT_COLOR: Record<EarningsMarker["outcome"], string> = {
  beat: "#16a34a",
  miss: "#dc2626",
  meet: "#9ca3af",
  unknown: "#9ca3af",
};

function formatXTick(epochMs: number): string {
  const d = new Date(epochMs);
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

function formatYTick(v: number): string {
  return `$${v.toFixed(0)}`;
}

function PriceChartTooltip({
  active, payload, markerMap,
}: {
  active?: boolean;
  payload?: Array<{ payload: { date: string; close: number; epochMs: number } }>;
  markerMap: Map<string, EarningsMarker>;
}) {
  if (!active || !payload?.length) return null;
  const { date, close } = payload[0].payload;
  const marker = markerMap.get(date);
  return (
    <div className="rounded-lg border bg-card shadow-md px-3 py-2 text-xs min-w-[140px]">
      <p className="font-medium text-foreground mb-1">{date}</p>
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

function PriceChart({ symbol }: { symbol: string }) {
  const [period, setPeriod] = useState<ChartPeriod>("1y");
  const [chartData, setChartData] = useState<TickerChart | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.tickers.chart(symbol, period).then((d) => {
      setChartData(d);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [symbol, period]);

  // Build epoch-keyed data for recharts
  const { lineData, markerMap } = useMemo(() => {
    const empty = {
      lineData: [] as Array<{ date: string; epochMs: number; close: number }>,
      markerMap: new Map<string, EarningsMarker>(),
    };
    if (!chartData) return empty;
    const mm = new Map<string, EarningsMarker>(
      chartData.earnings_markers.map((m) => [m.date, m])
    );
    const ld = chartData.history.map((p) => ({
      date: p.date,
      epochMs: new Date(p.date + "T12:00:00Z").getTime(),
      close: p.close,
    }));
    return { lineData: ld, markerMap: mm };
  }, [chartData]);

  // x-axis ticks: sample ~6 evenly spaced
  const xTicks = useMemo(() => {
    if (lineData.length < 2) return [];
    const n = Math.min(6, lineData.length);
    return Array.from({ length: n }, (_, i) =>
      lineData[Math.floor((i / (n - 1)) * (lineData.length - 1))].epochMs
    );
  }, [lineData]);

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

  const isUp = lineData[lineData.length - 1].close >= lineData[0].close;
  const lineColor = isUp ? "#16a34a" : "#dc2626";

  return (
    <div className="mt-6 rounded-lg border bg-card px-4 pt-4 pb-2">
      {/* Period selector */}
      <div className="flex gap-1 mb-3">
        {CHART_PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
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
            dataKey="epochMs"
            type="number"
            domain={["dataMin", "dataMax"]}
            scale="time"
            ticks={xTicks}
            tickFormatter={formatXTick}
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={["auto", "auto"]}
            tickFormatter={formatYTick}
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            axisLine={false}
            tickLine={false}
            width={50}
          />
          <Tooltip
            content={<PriceChartTooltip markerMap={markerMap} />}
            cursor={{ stroke: "hsl(var(--muted-foreground))", strokeWidth: 1, strokeDasharray: "4 2" }}
          />

          {/* Vertical dashed lines at each earnings date */}
          {markerDates.map((m) => (
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
            type="monotone"
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* Legend */}
      {markerDates.length > 0 && (
        <div className="flex gap-4 mt-1 px-1 pb-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-600" /> Beat
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-600" /> Miss
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-400" /> Meet / Unknown
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

function fmtIV(iv: number | null): string {
  return iv == null ? "—" : `${(iv * 100).toFixed(1)}%`;
}
function fmtPctDecimal(v: number | null, digits = 1): string {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

// ── Tooltip component ─────────────────────────────────────────────────────────

function Tip({ children, text }: { children: React.ReactNode; text: string }) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const ref = useRef<HTMLSpanElement>(null);

  function show() { if (ref.current) setRect(ref.current.getBoundingClientRect()); }
  function hide() { setRect(null); }

  return (
    <>
      <span
        ref={ref}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        className="inline-flex items-center cursor-help"
      >
        {children}
      </span>
      {rect && createPortal(
        <div
          role="tooltip"
          style={{
            position: "fixed",
            // Appear above the trigger; clamp horizontally so it never runs off-screen
            top:  rect.top - 8,
            left: Math.max(8, Math.min(
              (typeof window !== "undefined" ? window.innerWidth : 1200) - 248,
              rect.left + rect.width / 2 - 120,
            )),
            transform: "translateY(-100%)",
            zIndex: 9999,
          }}
          className="w-60 rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 shadow-xl pointer-events-none whitespace-normal leading-relaxed"
        >
          {text}
        </div>,
        document.body,
      )}
    </>
  );
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

// ── IV heatmap helper ─────────────────────────────────────────────────────────

function ivHeatBg(iv: number | null, minIV: number, maxIV: number): React.CSSProperties {
  if (iv == null || minIV >= maxIV) return {};
  const t = Math.max(0, Math.min(1, (iv - minIV) / (maxIV - minIV)));
  // cool blue (low IV) → warm orange (high IV), subtle opacity
  const r = Math.round(59  + t * (249 - 59));
  const g = Math.round(130 + t * (115 - 130));
  const b = Math.round(246 + t * (22  - 246));
  const a = 0.10 + t * 0.12;
  return { backgroundColor: `rgba(${r},${g},${b},${a.toFixed(2)})` };
}

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
          <p className="mt-1.5 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded px-2.5 py-1.5">
            This covers the full period to expiration — <strong>{daysPast} days past the {em.earnings_date} earnings</strong>.
            It reflects total vol over that window, not just the earnings event.
          </p>
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

// ── OptionsChainView ──────────────────────────────────────────────────────────

function OptionsChainView({
  chain,
  onExpiration,
}: {
  chain: OptionsChain;
  onExpiration: (exp: string) => void;
}) {
  const allStrikes = useMemo(
    () => Array.from(new Set([...chain.calls, ...chain.puts].map((c) => c.strike))).sort((a, b) => a - b),
    [chain.calls, chain.puts],
  );
  const callMap = useMemo(
    () => new Map<number, OptionContract>(chain.calls.map((c) => [c.strike, c])),
    [chain.calls],
  );
  const putMap = useMemo(
    () => new Map<number, OptionContract>(chain.puts.map((p) => [p.strike, p])),
    [chain.puts],
  );

  // A contract is questionable if the backend set data_quality_flag
  function isQuestionable(c: OptionContract | undefined): boolean {
    return c != null && c.data_quality_flag != null;
  }

  // IV heatmap: only use trustworthy contracts for the color scale
  const { minIV, maxIV } = useMemo(() => {
    const ivs = [...chain.calls, ...chain.puts]
      .filter((c) => !isQuestionable(c))
      .map((c) => c.implied_volatility)
      .filter((v): v is number => v != null);
    return { minIV: ivs.length ? Math.min(...ivs) : 0, maxIV: ivs.length ? Math.max(...ivs) : 1 };
  }, [chain.calls, chain.puts]);

  return (
    <div className="space-y-3">
      {/* Expiration selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm text-muted-foreground">Expiration:</label>
        <select
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={chain.expiration}
          onChange={(e) => onExpiration(e.target.value)}
        >
          {chain.available_expirations.map((exp) => (
            <option key={exp} value={exp}>{exp}</option>
          ))}
        </select>
      </div>

      {/* Chain table */}
      <div className="rounded-lg border bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-3 py-2.5 text-right font-medium text-muted-foreground">
                  <Tip text={TIPS.bid}>
                    <span className="underline decoration-dotted underline-offset-2">Call Bid</span>
                  </Tip>
                </th>
                <th className="px-3 py-2.5 text-right font-medium text-muted-foreground">
                  <Tip text={TIPS.ask}>
                    <span className="underline decoration-dotted underline-offset-2">Call Ask</span>
                  </Tip>
                </th>
                <th className="px-3 py-2.5 text-right font-medium text-muted-foreground">
                  <Tip text={TIPS.iv}>
                    <span className="underline decoration-dotted underline-offset-2">Call IV</span>
                  </Tip>
                </th>
                <th className="px-3 py-2.5 text-center font-medium text-muted-foreground">
                  <Tip text={TIPS.strike}>
                    <span className="underline decoration-dotted underline-offset-2">Strike</span>
                  </Tip>
                </th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                  <Tip text={TIPS.iv}>
                    <span className="underline decoration-dotted underline-offset-2">Put IV</span>
                  </Tip>
                </th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                  <Tip text={TIPS.bid}>
                    <span className="underline decoration-dotted underline-offset-2">Put Bid</span>
                  </Tip>
                </th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                  <Tip text={TIPS.ask}>
                    <span className="underline decoration-dotted underline-offset-2">Put Ask</span>
                  </Tip>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {allStrikes.map((strike) => {
                const call = callMap.get(strike);
                const put  = putMap.get(strike);
                const isAtm = call?.is_atm || put?.is_atm;
                const callQ = isQuestionable(call);
                const putQ  = isQuestionable(put);
                const deadCls = "text-muted-foreground/50";
                return (
                  <tr
                    key={strike}
                    className={cn(
                      "transition-colors",
                      isAtm ? "bg-blue-50 dark:bg-blue-900/20" : "hover:bg-muted/30",
                    )}
                  >
                    {/* Call bid */}
                    <td className={cn("px-3 py-2 text-right tabular-nums", callQ && deadCls)}>
                      {callQ ? "—" : (call?.bid != null ? call.bid.toFixed(2) : "—")}
                    </td>
                    {/* Call ask */}
                    <td className={cn("px-3 py-2 text-right tabular-nums", callQ && deadCls)}>
                      {callQ ? "—" : (call?.ask != null ? call.ask.toFixed(2) : "—")}
                    </td>
                    {/* Call IV — heatmap tinted only for trustworthy contracts */}
                    <td
                      className={cn("px-3 py-2 text-right tabular-nums font-medium", callQ && deadCls)}
                      style={callQ ? {} : ivHeatBg(call?.implied_volatility ?? null, minIV, maxIV)}
                    >
                      {callQ ? "—" : fmtIV(call?.implied_volatility ?? null)}
                    </td>
                    {/* Strike — always shown */}
                    <td className="px-3 py-2 text-center font-semibold tabular-nums">
                      {strike.toFixed(0)}
                      {isAtm && (
                        <Tip text={TIPS.atm}>
                          <span className="ml-1 text-xs font-normal text-blue-600 dark:text-blue-400 underline decoration-dotted underline-offset-2">
                            ATM
                          </span>
                        </Tip>
                      )}
                    </td>
                    {/* Put IV — heatmap tinted only for trustworthy contracts */}
                    <td
                      className={cn("px-3 py-2 text-left tabular-nums font-medium", putQ && deadCls)}
                      style={putQ ? {} : ivHeatBg(put?.implied_volatility ?? null, minIV, maxIV)}
                    >
                      {putQ ? "—" : fmtIV(put?.implied_volatility ?? null)}
                    </td>
                    {/* Put bid */}
                    <td className={cn("px-3 py-2 text-left tabular-nums", putQ && deadCls)}>
                      {putQ ? "—" : (put?.bid != null ? put.bid.toFixed(2) : "—")}
                    </td>
                    {/* Put ask */}
                    <td className={cn("px-3 py-2 text-left tabular-nums", putQ && deadCls)}>
                      {putQ ? "—" : (put?.ask != null ? put.ask.toFixed(2) : "—")}
                    </td>
                  </tr>
                );
              })}
              {allStrikes.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                    No options data available for this expiration.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="px-3 py-2 text-xs text-muted-foreground border-t bg-muted/20">
          IV columns are color-shaded from cool (low) to warm (high) — warmer = pricier vol.
          Options data may be delayed after hours. Options are leveraged instruments — use for analytical context only.
        </p>
      </div>
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

// ── Status types ──────────────────────────────────────────────────────────────

type TickerStatus   = "loading" | "found" | "missing" | "error";
type SectionStatus  = "loading" | "done" | "error";

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

  const [quote, setQuote]             = useState<TickerQuote | null>(null);

  const [expectedMove, setExpectedMove]   = useState<ExpectedMove | null>(null);
  const [emStatus, setEmStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");
  const [optionsChain, setOptionsChain]   = useState<OptionsChain | null>(null);
  const [ocStatus, setOcStatus]           = useState<"loading" | "done" | "empty" | "error">("loading");
  const [selectedExpiration, setSelectedExpiration] = useState<string | null>(null);

  const [note, setNote]               = useState<ResearchNote | null>(null);
  const [noteStatus, setNoteStatus]   = useState<"loading" | "empty" | "done" | "error">("loading");
  const [generating, setGenerating]   = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [verificationOpen, setVerificationOpen] = useState(false);

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
  }, [upperSymbol]);

  useEffect(() => {
    api.tickers.quote(upperSymbol).then(setQuote).catch(() => null);
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
    api.researchNotes
      .get(upperSymbol)
      .then((n) => { setNote(n); setNoteStatus("done"); })
      .catch((e: Error) => {
        if (e.message.startsWith("API 404")) { setNoteStatus("empty"); }
        else { setNoteStatus("error"); }
      });
  }, [upperSymbol]);

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      const n = await api.researchNotes.generate(upperSymbol);
      setNote(n);
      setNoteStatus("done");
    } catch (e: unknown) {
      setGenerateError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setGenerating(false);
    }
  }

  function handleRegenerate() {
    if (!window.confirm("Regenerate this research note? This uses ~$0.30 in API credit.")) return;
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
        <div className="mt-6">
          <h1 className="text-5xl font-bold tracking-tight">{ticker.symbol}</h1>
          {ticker.name && (
            <p className="text-xl text-muted-foreground mt-2">{ticker.name}</p>
          )}
        </div>

        {/* Live price header */}
        {quote && quote.price != null && (
          <div className="mt-5 flex items-center gap-5 flex-wrap">
            <div className="flex items-baseline gap-2.5">
              <span className="text-3xl font-bold tabular-nums tracking-tight">
                ${quote.price.toFixed(2)}
              </span>
              {quote.change != null && quote.change_pct != null && (
                <span
                  className={cn(
                    "text-sm font-medium tabular-nums",
                    quote.change >= 0
                      ? "text-green-600 dark:text-green-400"
                      : "text-red-600 dark:text-red-400",
                  )}
                >
                  {quote.change >= 0 ? "+" : ""}
                  {quote.change.toFixed(2)}{" "}
                  ({quote.change_pct >= 0 ? "+" : ""}
                  {quote.change_pct.toFixed(2)}%)
                </span>
              )}
            </div>
            {quote.high != null && quote.low != null && (
              <span className="text-xs text-muted-foreground ml-auto">
                H&nbsp;{quote.high.toFixed(2)} · L&nbsp;{quote.low.toFixed(2)}
              </span>
            )}
          </div>
        )}

        {/* Interactive price chart with earnings markers */}
        <PriceChart symbol={upperSymbol} />

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
              No historical reactions found. Run{" "}
              <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
                make seed-reactions TICKER={ticker.symbol}
              </code>{" "}
              to seed data.
            </div>
          )}
          {reactionStatus === "done" && reactions.length > 0 && (
            <ReactionsTable reactions={reactions} />
          )}
        </div>

        {/* Research Note */}
        <div className="mt-10 mb-10">
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
              {!generating && (
                <button
                  onClick={() => void handleGenerate()}
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  Generate Research Note
                </button>
              )}
            </div>
          )}

          {noteStatus === "empty" && !generating && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center">
              <p className="text-sm font-medium mb-1">No research note generated yet.</p>
              <p className="text-xs text-muted-foreground mb-5">
                AI-generated summary using SEC filings + earnings history · ~40 seconds · ~$0.17 in API credit (generation ~$0.02 + Opus verification ~$0.15)
              </p>
              <button
                onClick={() => void handleGenerate()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Generate Research Note
              </button>
            </div>
          )}

          {generating && (
            <div className="rounded-lg border bg-card px-6 py-10 text-center text-sm text-muted-foreground animate-pulse">
              Generating + verifying research note… this takes ~40 seconds
            </div>
          )}

          {generateError && !generating && (
            <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
              Generation failed: {generateError}
            </div>
          )}

          {noteStatus === "done" && note && !generating && (
            <div className="rounded-lg border bg-card">
              {/* Ungrounded filing warning — shown when no SEC filing was available */}
              {note.source_filings.length === 0 && (
                <div className="flex items-start gap-3 px-6 py-3 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-900 text-sm text-amber-700 dark:text-amber-400">
                  <span className="mt-0.5 shrink-0">⚠</span>
                  <span>
                    <strong>Generated without SEC filing.</strong>{" "}
                    This note is based on general knowledge and earnings history only — not grounded in a current 10-Q or 10-K. Treat all claims with extra caution.
                  </span>
                </div>
              )}

              {/* Contradicted claims warning */}
              {note.verification && note.verification.summary.contradicted > 0 && (
                <div className="flex items-start gap-3 px-6 py-3 bg-red-50 dark:bg-red-950/30 border-b border-red-200 dark:border-red-900 text-sm text-red-700 dark:text-red-400">
                  <span className="mt-0.5 shrink-0">⚠</span>
                  <span>
                    <strong>Verification found {note.verification.summary.contradicted} contradicted claim{note.verification.summary.contradicted !== 1 ? "s" : ""}.</strong>{" "}
                    See the verification section below for details. Consider regenerating.
                  </span>
                </div>
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

              {/* Note content */}
              <div className="px-6 py-5 prose prose-sm dark:prose-invert max-w-none
                prose-headings:text-foreground prose-headings:font-semibold
                prose-p:text-foreground/90 prose-li:text-foreground/90
                prose-strong:text-foreground">
                <ReactMarkdown>{note.content}</ReactMarkdown>
              </div>

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

        {/* ── Options & Expected Move ────────────────────────────────────────── */}
        <div className="mt-10 mb-10">
          <h2 className="text-lg font-semibold mb-4">Options & Expected Move</h2>

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

          <div className="mt-6">
            {selectedExpiration !== null && ocStatus === "loading" && (
              <div className="animate-pulse space-y-3">
                <div className="h-8 bg-muted rounded w-48" />
                <div className="h-64 bg-muted rounded-lg" />
              </div>
            )}
            {ocStatus === "error" && (
              <p className="text-sm text-muted-foreground">Could not load options chain.</p>
            )}
            {ocStatus === "empty" && (
              <p className="text-sm text-muted-foreground">No options chain data available.</p>
            )}
            {ocStatus === "done" && optionsChain && (
              <OptionsChainView
                chain={optionsChain}
                onExpiration={setSelectedExpiration}
              />
            )}
          </div>

          {/* Education — rendered when both datasets are ready */}
          {emStatus === "done" && expectedMove && ocStatus === "done" && optionsChain && (
            <OptionsEducation
              em={expectedMove}
              chain={optionsChain}
              symbol={upperSymbol}
            />
          )}
        </div>

      </div>
    </main>
  );
}
