"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { api, type AlertPickLedgerItem } from "@/lib/api";

export default function AlertsTradesPage() {
  const [picks, setPicks] = useState<AlertPickLedgerItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.theses.alertPicks();
        if (!cancelled) setPicks(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load picks");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const openPicks = picks.filter((p) => p.status === "open");
  const avgUnrealized =
    openPicks.length > 0
      ? openPicks.reduce((sum, p) => sum + (p.unrealized_move_pct ?? 0), 0) / openPicks.length
      : null;

  return (
    <div className="mx-auto max-w-4xl space-y-8 py-8 px-4">
      <div>
        <h1 className="text-3xl font-display font-bold tracking-tight">Alert&apos;s Trades</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Every pick Alert has made, scored against the market.
        </p>
      </div>

      {/* Summary header */}
      {!loading && !error && picks.length > 0 && (
        <div className="flex gap-6 text-sm">
          <div>
            <span className="text-muted-foreground">Total picks</span>{" "}
            <span className="font-semibold">{picks.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Open</span>{" "}
            <span className="font-semibold">{openPicks.length}</span>
          </div>
          {avgUnrealized !== null && (
            <div>
              <span className="text-muted-foreground">Avg unrealized</span>{" "}
              <span
                className={cn(
                  "font-semibold font-mono",
                  avgUnrealized > 0 ? "text-green-600 dark:text-green-400" :
                  avgUnrealized < 0 ? "text-red-600 dark:text-red-400" : ""
                )}
              >
                {avgUnrealized >= 0 ? "+" : ""}{avgUnrealized.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <p className="text-sm text-muted-foreground animate-pulse">Loading picks...</p>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-5 py-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && picks.length === 0 && (
        <div className="rounded-lg border border-dashed px-8 py-12 text-center">
          <p className="text-lg font-medium">No picks yet</p>
          <p className="text-sm text-muted-foreground mt-1">
            Go to <a href="/build" className="underline hover:text-foreground">Build a Trade</a> and
            let Alert decide on a ticker.
          </p>
        </div>
      )}

      {/* Pick cards */}
      {!loading && !error && picks.length > 0 && (
        <div className="space-y-3">
          {picks.map((pick) => {
            const isBullish = pick.picked_direction === "bullish";
            const move = pick.unrealized_move_pct;
            // Direction-correct: bullish pick with stock up, or bearish pick with stock down
            const directionCorrect =
              move != null
                ? isBullish
                  ? move > 0
                  : move < 0
                : null;

            const expanded = expandedId === pick.id;

            return (
              <div
                key={pick.id}
                className="rounded-lg border bg-card px-5 py-4 space-y-3"
              >
                {/* Row 1: Symbol, direction badge, strategy */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold font-mono">{pick.symbol}</span>
                    <span
                      className={cn(
                        "px-2 py-0.5 rounded text-xs font-semibold uppercase",
                        isBullish
                          ? "bg-green-500/10 text-green-600 dark:text-green-400"
                          : "bg-red-500/10 text-red-600 dark:text-red-400"
                      )}
                    >
                      {pick.picked_direction}
                    </span>
                    {pick.vol_regime && (
                      <span className="text-xs text-muted-foreground">
                        {pick.vol_regime.replace("_", " ")}
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-muted-foreground tabular-nums whitespace-nowrap">
                    {pick.algo_version}
                  </span>
                </div>

                {/* Strategy line */}
                {pick.strategy && (
                  <p className="text-sm text-muted-foreground">
                    {pick.strategy}
                    {pick.expiration && (
                      <span className="ml-1">
                        · exp {new Date(pick.expiration + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                      </span>
                    )}
                  </p>
                )}

                {/* Row 2: Price marks + move */}
                <div className="flex items-baseline gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Entry</span>{" "}
                    <span className="font-mono font-medium">${pick.entry_price.toFixed(2)}</span>
                  </div>
                  {pick.current_price != null && (
                    <div>
                      <span className="text-muted-foreground">Now</span>{" "}
                      <span className="font-mono font-medium">${pick.current_price.toFixed(2)}</span>
                    </div>
                  )}
                  {move != null && (
                    <span
                      className={cn(
                        "font-mono font-semibold",
                        directionCorrect === true
                          ? "text-green-600 dark:text-green-400"
                          : directionCorrect === false
                            ? "text-red-600 dark:text-red-400"
                            : ""
                      )}
                    >
                      {move >= 0 ? "+" : ""}{move.toFixed(2)}%
                    </span>
                  )}

                  {/* Cost / risk metrics */}
                  <div className="ml-auto flex gap-3 text-xs text-muted-foreground">
                    {pick.cost_to_enter != null && (
                      <span>Cost ${pick.cost_to_enter.toFixed(2)}</span>
                    )}
                    {pick.max_loss != null && (
                      <span>Max loss ${pick.max_loss.toFixed(0)}</span>
                    )}
                    {pick.max_gain != null ? (
                      <span>Max gain ${pick.max_gain.toFixed(0)}</span>
                    ) : pick.cost_to_enter != null ? (
                      <span>Max gain unlimited</span>
                    ) : null}
                  </div>
                </div>

                {/* Row 3: Lean dots */}
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  {pick.leans.map((lean) => (
                    <div key={lean.signal} className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "w-2 h-2 rounded-full",
                          lean.direction === "bullish"
                            ? "bg-green-500"
                            : lean.direction === "bearish"
                              ? "bg-red-500"
                              : "bg-zinc-400"
                        )}
                      />
                      <span className="capitalize">{lean.signal}</span>
                    </div>
                  ))}
                  <span className="ml-auto tabular-nums">
                    {new Date(pick.generated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>

                {/* Expandable reasoning */}
                {pick.reasoning && (
                  <div>
                    <button
                      type="button"
                      onClick={() => setExpandedId(expanded ? null : pick.id)}
                      className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {expanded ? "Hide reasoning" : "Show reasoning"}
                    </button>
                    {expanded && (
                      <p className="text-xs text-muted-foreground mt-2 whitespace-pre-wrap leading-relaxed">
                        {pick.reasoning}
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
