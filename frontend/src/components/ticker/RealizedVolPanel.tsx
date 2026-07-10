"use client";

import type { RealizedVol } from "@/lib/api";
import { cn, rvRankShort } from "@/lib/utils";
import ExplainTip from "./ExplainTip";

function RealizedVolPanel({ rv, symbol }: { rv: RealizedVol; symbol: string }) {
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
            <ExplainTip term="rv rank" metric="rv_rank" symbol={symbol}>Realized-vol rank</ExplainTip>
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

export default RealizedVolPanel;
