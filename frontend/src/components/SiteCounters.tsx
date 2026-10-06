"use client";

import { useEffect, useState } from "react";
import { api, type SiteStats } from "@/lib/api";
import { CountUp } from "@/components/CountUp";
import { counterRows } from "@/lib/siteCounters";

/** Four live counts from /system/stats, the first thing under the hero: the number in the accent at the page's largest
 * numeric size with tabular figures, the label small and grey beneath, the as-of date as the number's hover title.
 * Renders nothing until the counts arrive and nothing at all when the API cannot be reached. */
export function SiteCounters() {
  const [stats, setStats] = useState<SiteStats | null>(null);
  useEffect(() => {
    api.system.stats().then(setStats).catch(() => {});
  }, []);
  const rows = counterRows(stats);
  if (!rows.length) return null;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-5 gap-y-12 max-w-6xl w-full mx-auto text-center">
      {rows.map((row) => (
        <div key={row.key} className="min-w-0">
          <CountUp value={row.value} title={row.title ?? undefined} className="stat-number font-display font-bold text-primary tabular-nums block whitespace-nowrap" />
          <p className={`font-mono text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-3 ${row.key === "contracts" ? "lg:whitespace-nowrap" : "whitespace-nowrap"}`}>{row.label}</p>
        </div>
      ))}
    </div>
  );
}
