"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type IvyActivity, type IvyWorksheetRow } from "@/lib/api";

function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
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

function LeanCell({ row, signal }: { row: IvyWorksheetRow; signal: string }) {
  if (!row.leans) return <td className="px-3 py-2.5" />;
  const lean = row.leans.find((l) => l.signal === signal);
  if (!lean) return <td className="px-3 py-2.5" />;
  const isNeutral = lean.direction === "neutral";
  return (
    <td className={`px-3 py-2.5 ${isNeutral ? "text-muted-foreground" : ""}`}>
      <span className="inline-flex items-center gap-1.5">
        <LeanDot direction={lean.direction} />
        <span className="capitalize">{lean.direction}</span>
      </span>
    </td>
  );
}

function Verdict({ row }: { row: IvyWorksheetRow }) {
  if (row.outcome === "picked" && row.pick) {
    const dir = row.leans?.find((l) => l.direction !== "neutral")?.direction;
    return (
      <span>
        <span className={dir === "bullish" ? "text-green-500" : dir === "bearish" ? "text-red-500" : ""}>
          Picked, {dir ?? "—"}
        </span>
        {row.pick.strategy && (
          <span className="text-muted-foreground"> · {row.pick.strategy}</span>
        )}
        {row.pick.expiration && (
          <span className="text-muted-foreground"> · {fmtDate(row.pick.expiration)}</span>
        )}
      </span>
    );
  }
  if (row.outcome === "picked") {
    const dir = row.leans?.find((l) => l.direction !== "neutral")?.direction;
    return (
      <span className={dir === "bullish" ? "text-green-500" : dir === "bearish" ? "text-red-500" : ""}>
        Picked, {dir ?? "—"}
      </span>
    );
  }
  const labels: Record<string, string> = {
    mixed_evidence: "Passed, mixed evidence",
    no_fresh_chain: "Passed, no fresh options data",
    open_pick_exists: "Passed, open pick exists",
    cap_reached: "Passed, cap reached",
    error: "Could not price",
  };
  return <span className="text-muted-foreground">{labels[row.outcome] ?? row.outcome}</span>;
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
          Ivy has not run yet tonight.
        </p>
      </div>
    );
  }

  const pickedCount = activity.picked;
  const passedCount = activity.evaluated - pickedCount;

  return (
    <div className="py-6 pb-14">
      <p className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">
        Overnight worksheet · {fmtDate(activity.run_date)}
      </p>
      <p className="text-lg text-muted-foreground mt-2">
        Ivy evaluated {activity.evaluated} names on {fmtDate(activity.run_date)}, picked {pickedCount}, passed on {passedCount}.
      </p>

      <div className="overflow-x-auto mt-6">
        <table className="min-w-[700px] w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              {["Symbol", "Reports", "Earnings", "Analyst", "Momentum", "Verdict"].map((col) => (
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
                  {row.earnings_date ? fmtDate(row.earnings_date) : "—"}
                </td>
                <LeanCell row={row} signal="earnings" />
                <LeanCell row={row} signal="analyst" />
                <LeanCell row={row} signal="momentum" />
                <td className="px-3 py-2.5">
                  <Verdict row={row} />
                </td>
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
