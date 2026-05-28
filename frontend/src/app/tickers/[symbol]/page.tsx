"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, notFound } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import { api, type Ticker, type Event, type EventType, type EarningsOutcome, type HistoricalReaction, type ResearchNote } from "@/lib/api";
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

// ── Stat strip ────────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium">{value ?? "—"}</span>
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

  const [note, setNote]               = useState<ResearchNote | null>(null);
  const [noteStatus, setNoteStatus]   = useState<"loading" | "empty" | "done" | "error">("loading");
  const [generating, setGenerating]   = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

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
                AI-generated summary using SEC filings + earnings history · ~20 seconds · ~$0.30 in API credit
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
              Generating research note… this takes ~20 seconds
            </div>
          )}

          {generateError && !generating && (
            <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
              Generation failed: {generateError}
            </div>
          )}

          {noteStatus === "done" && note && !generating && (
            <div className="rounded-lg border bg-card">
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
              <div className="px-6 py-5 prose prose-sm dark:prose-invert max-w-none
                prose-headings:text-foreground prose-headings:font-semibold
                prose-p:text-foreground/90 prose-li:text-foreground/90
                prose-strong:text-foreground">
                <ReactMarkdown>{note.content}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
