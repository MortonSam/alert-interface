"use client";

import { NIGHT_SUMMARY_KEY, PRIVATE_LEDGER_BODY, PRIVATE_LEDGER_TITLE, nightSummary } from "@/lib/ivyOutcomes";
import EncodingLegend from "@/components/EncodingLegend";
import { pickMove, pickResult, pickResultLegend } from "@/lib/encodings/pickResult";
import { useIvyRule } from "@/lib/useIvyRule";
import { type IvyRule, exitRuleSentence, fmtLongDate } from "@/lib/ivyRule";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { averagePnlPct, fmtPnlPct } from "@/lib/pnl";
import { api, type AlertPickLedgerItem, type IvyActivity } from "@/lib/api";
import { capture } from "@/lib/analytics";

const EXP_TAIL_RE = /\s*(?:;\s*max gain.*?)?\s+at\s+\d{4}-\d{2}-\d{2}\s+expiration\s*$/i;

function fmtQuoteTime(unix: number | null | undefined): string {
  if (unix == null) return "";
  const d = new Date(unix * 1000);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function stripExpTail(strategy: string | null): string | null {
  if (!strategy) return strategy;
  return strategy.replace(EXP_TAIL_RE, "");
}

function fmtPnlDollars(d: number): string {
  return d >= 0 ? `+$${d.toFixed(2)}` : `-$${Math.abs(d).toFixed(2)}`;
}
function fmtMarkDate(d: string): string {
  return new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function PickCard({
  pick,
  expanded,
  onToggle,
  isClosed,
  rule,
}: {
  pick: AlertPickLedgerItem;
  expanded: boolean;
  onToggle: () => void;
  isClosed: boolean;
  rule: IvyRule | null;
}) {
  const isBullish = pick.picked_direction === "bullish";
  const move = pick.unrealized_move_pct;

  const displayStrategy = stripExpTail(pick.strategy);

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-3">
      {/* Row 1: Symbol, direction badge, HIT/MISS badge */}
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
          {isClosed && pick.direction_hit != null && (
            <span
              title={pickResult(pick.direction_hit)?.detail}
              className={cn("px-2 py-0.5 rounded text-xs font-bold uppercase", pickResult(pick.direction_hit)?.className)}
            >
              {pickResult(pick.direction_hit)?.label}
            </span>
          )}
          {pick.vol_regime && (
            <span className="text-xs text-muted-foreground">
              {pick.vol_regime.replace("_", " ")}
            </span>
          )}
        </div>
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground tabular-nums whitespace-nowrap">
          {pick.algo_version}
          {pick.source === "nightly" && (
            <span className="inline-flex items-center rounded-full bg-cool/10 text-cool px-2 py-0.5 text-[10px] font-semibold tracking-wide">
              nightly
            </span>
          )}
        </span>
      </div>

      {/* Strategy line */}
      {displayStrategy && (
        <p className="text-sm text-muted-foreground">
          {displayStrategy}
          {pick.expiration && (
            <span className="ml-1">
              · exp {new Date(pick.expiration + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
            </span>
          )}
        </p>
      )}

      {/* Exit rule line */}
      {pick.exit_date && !isClosed && (
        <p className="text-xs text-muted-foreground">
          {rule ? exitRuleSentence(rule, new Date(pick.exit_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })) : `Exit: ${new Date(pick.exit_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}`}
        </p>
      )}
      {pick.exit_date && isClosed && (
        <p className="text-xs text-muted-foreground">
          Closed {new Date(pick.exit_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })} at planned exit
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
            <span className="text-muted-foreground">{isClosed ? "Close" : "Now"}</span>{" "}
            <span className="font-mono font-medium">${pick.current_price.toFixed(2)}</span>
            {!isClosed && pick.quote_ts != null && (
              <span className="text-[10px] text-muted-foreground/50 ml-1">
                {fmtQuoteTime(pick.quote_ts)}
              </span>
            )}
          </div>
        )}
        {move != null && (
          <span
            title={pickMove(pick.picked_direction, move).label}
            className={cn("font-mono font-semibold", pickMove(pick.picked_direction, move).className)}
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
          ) : pick.cost_to_enter != null && pick.picked_direction === "bullish" ? (
            <span>Max gain unlimited</span>
          ) : pick.cost_to_enter != null && pick.suggested_strike != null ? (
            <span>Max gain ${((pick.suggested_strike - pick.cost_to_enter) * 100).toFixed(0)}</span>
          ) : null}
        </div>
      </div>

      {/* Option P&L line */}
      {isClosed && pick.option_pnl_dollars != null && pick.option_pnl_pct != null && (
        <div className="text-sm">
          <span className="text-muted-foreground">Settled</span>{" "}
          <span
            className={cn(
              "font-mono font-semibold",
              pick.option_pnl_dollars >= 0
                ? "text-green-600 dark:text-green-400"
                : "text-red-600 dark:text-red-400"
            )}
          >
            {fmtPnlDollars(pick.option_pnl_dollars)} ({fmtPnlPct(pick.option_pnl_pct)})
          </span>
          {pick.stock_move_5d != null && (
            <span className="text-muted-foreground ml-3">
              stock {pick.stock_move_5d >= 0 ? "+" : ""}{pick.stock_move_5d.toFixed(2)}%
            </span>
          )}
        </div>
      )}
      {!isClosed && pick.cost_to_enter != null && (
        <div className="text-sm">
          <span className="text-muted-foreground">Option</span>{" "}
          <span className="font-mono">${pick.cost_to_enter.toFixed(2)} entry</span>
          {pick.option_mid != null ? (
            <>
              <span className="text-muted-foreground"> → </span>
              <span className="font-mono">${pick.option_mid.toFixed(2)}</span>
              {pick.option_pnl_dollars != null && pick.option_pnl_pct != null && (
                <>
                  {"   "}
                  <span
                    className={cn(
                      "font-mono font-semibold",
                      pick.option_pnl_dollars >= 0
                        ? "text-green-600 dark:text-green-400"
                        : "text-red-600 dark:text-red-400"
                    )}
                  >
                    {fmtPnlDollars(pick.option_pnl_dollars)} ({fmtPnlPct(pick.option_pnl_pct)})
                  </span>
                </>
              )}
              {pick.option_mark_as_of && (
                <span className="text-xs text-muted-foreground ml-2">
                  as of {fmtMarkDate(pick.option_mark_as_of)}
                </span>
              )}
            </>
          ) : (
            <>
              <span className="text-muted-foreground"> → </span>
              <span className="text-muted-foreground italic">n/a</span>
              {pick.option_mark_note && (
                <span className="text-xs text-muted-foreground ml-2">
                  {pick.option_mark_note}
                </span>
              )}
            </>
          )}
        </div>
      )}

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

      {/* v2 Receipt */}
      {pick.receipt && (
        <div className="rounded bg-muted/50 px-3 py-2 text-xs space-y-1">
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-muted-foreground">
            {pick.receipt.n_comparable != null && (
              <span>{pick.receipt.n_comparable as number} prior events</span>
            )}
            {pick.receipt.base_rate_up_5d != null && pick.receipt.base_rate_n != null && (
              <span>{((pick.receipt.base_rate_up_5d as number) * 100).toFixed(0)}% up at 5d (n={pick.receipt.base_rate_n as number})</span>
            )}
            {pick.receipt.momentum_20d != null && (
              <span>momentum {(pick.receipt.momentum_20d as number) >= 0 ? "+" : ""}{(pick.receipt.momentum_20d as number).toFixed(1)}%</span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-muted-foreground">
            {pick.receipt.expected_pct != null && (
              <span>expected |5d| {(pick.receipt.expected_pct as number).toFixed(1)}%</span>
            )}
            {pick.receipt.implied_pct != null && (
              <span>implied {(pick.receipt.implied_pct as number).toFixed(1)}%</span>
            )}
            {pick.exit_date && (
              <span>exit {new Date(pick.exit_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
            )}
          </div>
        </div>
      )}

      {/* Picked by Ivy attribution */}
      <p className="text-[10px] text-muted-foreground/60">
        Picked by Ivy {new Date(pick.generated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}{pick.model_used ? ` · ${pick.model_used}` : ""}
      </p>

      {/* Expandable reasoning */}
      {pick.reasoning && (
        <div>
          <button
            type="button"
            onClick={onToggle}
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
}

export default function IvyTradesPage() {
  const ivy = useIvyRule();
  const [picks, setPicks] = useState<AlertPickLedgerItem[]>([]);
  const [activity, setActivity] = useState<IvyActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [data, act] = await Promise.all([
          api.theses.alertPicks(2),
          api.theses.ivyActivity(),
        ]);
        if (!cancelled) {
          setPicks(data);
          setActivity(act);
          capture("ivy_trades_viewed");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load picks");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const openPicks = picks.filter((p) => p.status === "open");
  const closedPicks = picks.filter((p) => p.status === "closed");

  const avgUnrealized =
    openPicks.length > 0
      ? (() => {
          const withData = openPicks.filter((p) => p.unrealized_move_pct != null);
          return withData.length > 0
            ? withData.reduce((sum, p) => sum + p.unrealized_move_pct!, 0) / withData.length
            : null;
        })()
      : null;

  // Closed stats
  const scoredClosed = closedPicks.filter((p) => p.direction_hit != null);
  const directionHits = scoredClosed.filter((p) => p.direction_hit).length;
  const directionMisses = scoredClosed.length - directionHits;
  const pnlDollars = closedPicks.filter((p) => p.option_pnl_dollars != null).map((p) => p.option_pnl_dollars!);
  const totalOptionPnl = pnlDollars.length > 0 ? pnlDollars.reduce((a, b) => a + b, 0) : null;
  const avgOptionPnlPct = averagePnlPct(closedPicks.map((p) => p.option_pnl_pct));

  // Open option P&L (from chain marks)
  const markedOpen = openPicks.filter((p) => p.option_pnl_dollars != null);
  const openOptionPnl = markedOpen.length > 0
    ? markedOpen.reduce((sum, p) => sum + p.option_pnl_dollars!, 0)
    : null;

  return (
    <div className="py-8 space-y-8">
      {/* Private preview label */}
      {!loading && !error && picks.length > 0 && activity && !activity.ledger_public && (
        <p className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
          Private preview
        </p>
      )}

      {/* Summary header */}
      {!loading && !error && picks.length > 0 && (<>
        <div className="flex flex-wrap gap-6 text-sm">
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
              <span className="text-muted-foreground">Avg stock move (open)</span>{" "}
              <span className="font-semibold font-mono text-muted-foreground">
                {avgUnrealized >= 0 ? "+" : ""}{avgUnrealized.toFixed(2)}%
              </span>
            </div>
          )}
          {scoredClosed.length > 0 && (
            <>
              <div>
                <span className="text-muted-foreground">Direction</span>{" "}
                <span className="font-semibold">{directionHits}-{directionMisses}</span>
              </div>
              {totalOptionPnl !== null && (
                <div>
                  <span className="text-muted-foreground">Option P&L</span>{" "}
                  <span
                    className={cn(
                      "font-semibold font-mono",
                      totalOptionPnl > 0 ? "text-green-600 dark:text-green-400" :
                      totalOptionPnl < 0 ? "text-red-600 dark:text-red-400" : ""
                    )}
                  >
                    {totalOptionPnl >= 0 ? "+$" : "-$"}{Math.abs(totalOptionPnl).toFixed(2)}
                  </span>
                </div>
              )}
              {avgOptionPnlPct !== null && (
                <div>
                  <span className="text-muted-foreground">Avg P&L %</span>{" "}
                  <span
                    className={cn(
                      "font-semibold font-mono",
                      avgOptionPnlPct > 0 ? "text-green-600 dark:text-green-400" :
                      avgOptionPnlPct < 0 ? "text-red-600 dark:text-red-400" : ""
                    )}
                  >
                    {avgOptionPnlPct >= 0 ? "+" : ""}{avgOptionPnlPct.toFixed(1)}%
                  </span>
                </div>
              )}
            </>
          )}
          {openOptionPnl !== null && (
            <div>
              <span className="text-muted-foreground">Open option P&L</span>{" "}
              <span
                className={cn(
                  "font-semibold font-mono",
                  openOptionPnl > 0 ? "text-green-600 dark:text-green-400" :
                  openOptionPnl < 0 ? "text-red-600 dark:text-red-400" : ""
                )}
              >
                {fmtPnlDollars(openOptionPnl)}
              </span>
              <span className="text-muted-foreground ml-1">
                {markedOpen.length} of {openPicks.length} marked
              </span>
            </div>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground/60 -mt-4">
          Hypothetical, unexecuted picks. No commissions, fees, or slippage.{" "}
          <a href="/disclosures" className="underline">See Disclosures</a>.
        </p>
      </>)}

      {/* Nightly evaluation summary */}
      {!loading && !error && activity?.run_date && (
        <p className="text-sm text-muted-foreground">
          {(() => {
            const rd = new Date(activity.run_date + "T12:00:00");
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const diff = Math.round((today.getTime() - new Date(rd.getFullYear(), rd.getMonth(), rd.getDate()).getTime()) / 86400000);
            if (diff <= 1) return "Last night";
            return `On ${rd.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
          })()} Ivy {nightSummary(activity)}. {NIGHT_SUMMARY_KEY}
        </p>
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
          {activity && !activity.ledger_public ? (
            <>
              <p className="text-lg font-medium">{PRIVATE_LEDGER_TITLE}</p>
              <p className="text-sm text-muted-foreground mt-1">{PRIVATE_LEDGER_BODY}</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">The ledger starts here</p>
              <p className="text-sm text-muted-foreground mt-1">
                {ivy ? `Ivy's ledger began ${fmtLongDate(ivy.rule.ledger_start)}. ` : ""}Every pick is recorded the moment it is made, before the outcome is known.
              </p>
            </>
          )}
        </div>
      )}

      {/* Open picks */}
      {!loading && !error && openPicks.length > 0 && (
        <div className="space-y-3">
          {openPicks.length < picks.length && (
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Open, newest first</h2>
          )}
          {openPicks.map((pick) => (
            <PickCard
              rule={ivy?.rule ?? null}
              key={pick.id}
              pick={pick}
              expanded={expandedId === pick.id}
              onToggle={() => setExpandedId(expandedId === pick.id ? null : pick.id)}
              isClosed={false}
            />
          ))}
        </div>
      )}

      {/* Closed picks */}
      {!loading && !error && closedPicks.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Closed, newest first</h2>
          <EncodingLegend items={pickResultLegend()} className="mt-1" />
          {closedPicks.map((pick) => (
            <PickCard
              rule={ivy?.rule ?? null}
              key={pick.id}
              pick={pick}
              expanded={expandedId === pick.id}
              onToggle={() => setExpandedId(expandedId === pick.id ? null : pick.id)}
              isClosed={true}
            />
          ))}
        </div>
      )}
    </div>
  );
}
