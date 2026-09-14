"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type IvyActivity, type IvyWorksheetRow } from "@/lib/api";

function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/* ── v2 cell renderers ─────────────────────────────────────────────── */

function MomentumCell({ row }: { row: IvyWorksheetRow }) {
  if (row.momentum_20d == null) return <td className="px-3 py-2.5 text-muted-foreground" />;
  const bad = row.momentum_20d <= -10;
  return (
    <td className={`px-3 py-2.5 tabular-nums ${bad ? "text-red-500" : "text-muted-foreground"}`}>
      {row.momentum_20d > 0 ? "+" : ""}{row.momentum_20d.toFixed(1)}%
    </td>
  );
}

function HistoryCell({ row }: { row: IvyWorksheetRow }) {
  if (row.prior_n == null) return <td className="px-3 py-2.5 text-muted-foreground" />;
  return (
    <td className="px-3 py-2.5 tabular-nums text-muted-foreground">
      {row.prior_n}
    </td>
  );
}

function ExpectedCell({ row }: { row: IvyWorksheetRow }) {
  if (row.expected_move_pct == null) return <td className="px-3 py-2.5 text-muted-foreground" />;
  return (
    <td className="px-3 py-2.5 tabular-nums text-muted-foreground">
      {row.expected_move_pct.toFixed(1)}%
    </td>
  );
}

function ImpliedCell({ row }: { row: IvyWorksheetRow }) {
  if (row.implied_move_pct == null) {
    return <td className="px-3 py-2.5 text-muted-foreground">no chain</td>;
  }
  return (
    <td className="px-3 py-2.5 tabular-nums text-muted-foreground">
      {row.implied_move_pct.toFixed(1)}%
    </td>
  );
}

function V2Verdict({ row }: { row: IvyWorksheetRow }) {
  if (!row.verdict) {
    return <td className="px-3 py-2.5 text-muted-foreground">{row.outcome}</td>;
  }
  const isPicked = row.verdict.startsWith("Picked");
  return (
    <td className={`px-3 py-2.5 ${isPicked ? "text-green-500" : "text-muted-foreground"}`}>
      {row.verdict}
    </td>
  );
}

export default function IvyDeskPage() {
  const [activity, setActivity] = useState<IvyActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.theses
      .ivyActivity()
      .then(setActivity)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="py-6 space-y-4">
        <div className="h-3 w-48 animate-pulse rounded bg-muted" />
        <div className="h-5 w-96 animate-pulse rounded bg-muted" />
        <div className="space-y-3 mt-6">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-8 animate-pulse rounded bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card px-6 py-10 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!activity || !activity.run_date || activity.rows.length === 0) {
    return (
      <div className="py-6">
        <p className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
          Overnight worksheet
        </p>
        <p className="text-lg text-muted-foreground mt-3">
          Ivy&apos;s first overnight worksheet appears after her next evaluation.
        </p>
      </div>
    );
  }

  const pickedCount = activity.picked;
  const passedCount = activity.evaluated - pickedCount;
  // v2 batch if any row has a verdict
  const isV2 = activity.rows.some((r) => r.verdict != null);
  const columns = isV2
    ? ["Symbol", "Reports", "Momentum", "History", "Expected", "Implied", "Verdict"]
    : ["Symbol", "Reports", "Earnings", "Analyst", "Momentum", "Verdict"];

  return (
    <div className="py-6 pb-14">
      {!activity.ledger_public && (
        <p className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground mb-2">
          Private preview
        </p>
      )}
      <p className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
        Overnight worksheet · {fmtDate(activity.run_date)}
      </p>
      <p className="text-lg text-muted-foreground mt-2">
        Ivy evaluated {activity.evaluated} names on {fmtDate(activity.run_date)}, picked {pickedCount}, passed on {passedCount}.
      </p>

      <div className="overflow-x-auto mt-6">
        <table className={`${isV2 ? "min-w-[800px]" : "min-w-[700px]"} w-full text-sm`}>
          <thead>
            <tr className="border-b border-border">
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-3 py-2 text-left font-mono text-xs uppercase tracking-wider text-muted-foreground font-normal"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activity.rows.map((row) => (
              <tr
                key={row.symbol}
                className={`border-b border-border/60 ${row.outcome === "picked" ? "border-l-2 border-l-primary" : ""}`}
              >
                <td className="px-3 py-2.5">
                  <Link
                    href={`/tickers/${row.symbol}`}
                    className="font-display font-semibold text-foreground hover:underline"
                  >
                    {row.symbol}
                  </Link>
                </td>
                <td className="px-3 py-2.5 tabular-nums text-muted-foreground">
                  {row.earnings_date ? fmtDate(row.earnings_date) : ""}
                </td>
                {isV2 ? (
                  <>
                    <MomentumCell row={row} />
                    <HistoryCell row={row} />
                    <ExpectedCell row={row} />
                    <ImpliedCell row={row} />
                    <V2Verdict row={row} />
                  </>
                ) : (
                  <>
                    {/* v1 lean columns (kept for old data, hidden by LEDGER_START) */}
                    {["earnings", "analyst", "momentum"].map((signal) => {
                      const lean = row.leans?.find((l) => l.signal === signal);
                      if (!lean) return <td key={signal} className="px-3 py-2.5" />;
                      const isNeutral = lean.direction === "neutral";
                      return (
                        <td key={signal} className={`px-3 py-2.5 ${isNeutral ? "text-muted-foreground" : ""}`}>
                          <span className="inline-flex items-center gap-1.5">
                            <span className={`w-2 h-2 rounded-full inline-block ${
                              lean.direction === "bullish" ? "bg-green-500" :
                              lean.direction === "bearish" ? "bg-red-500" : "bg-zinc-400"
                            }`} />
                            <span className="capitalize">{lean.direction}</span>
                          </span>
                        </td>
                      );
                    })}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {row.outcome}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground mt-4">
        Rows sorted by next earnings date. Chain coverage depends on market hours.
      </p>
    </div>
  );
}
