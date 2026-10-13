"use client";

import { useEffect, useState } from "react";
import { api, type SiteStats } from "@/lib/api";
import { CountUp } from "@/components/CountUp";
import { COUNTER_LABELS, counterRows } from "@/lib/siteCounters";
import { browserStorage, pickStats, readSnapshot, UNAVAILABLE_TITLE, writeSnapshot, type StatsSource } from "@/lib/siteStats";

/** Four live counts from /system/stats, the first thing under the hero: the number in the accent at the page's largest
 * numeric size with tabular figures, the label small and grey beneath, the as-of date as the number's hover title.
 * `initial` is the server's render (lib/siteStats: revalidated, kept when a refresh fails); the browser's stored snapshot and a
 * client refresh layer over it, and a failed refresh never removes a count. With nothing to show, the row keeps its place with
 * its four labels and a dash each. */
export function SiteCounters({ initial = null }: { initial?: SiteStats | null }) {
  const [picked, setPicked] = useState<{ stats: SiteStats | null; source: StatsSource }>(() => pickStats(null, initial, null));
  useEffect(() => {
    if (!initial) {
      const stored = readSnapshot(browserStorage());
      if (stored) setPicked(pickStats(null, null, stored));
    }
    api.system.stats()
      .then((fresh) => { setPicked(pickStats(fresh, initial, null)); writeSnapshot(browserStorage(), fresh); })
      .catch(() => { /* the last good counts stay */ });
  }, [initial]);
  const rows = counterRows(picked.stats);
  const stale = picked.source === "stored" ? " (last values this browser received)" : "";
  if (!rows.length) return <CountersUnavailable />;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-5 gap-y-12 max-w-6xl w-full mx-auto text-center">
      {rows.map((row) => (
        <div key={row.key} className="min-w-0">
          <CountUp value={row.value} title={row.title ? row.title + stale : undefined} className="stat-number font-display font-bold text-primary tabular-nums block whitespace-nowrap" />
          <p className={`font-mono text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-3 ${row.key === "contracts" ? "lg:whitespace-nowrap" : "whitespace-nowrap"}`}>{row.label}</p>
        </div>
      ))}
    </div>
  );
}

/** The row with no count to show: the four labels in place, a dash for each number, the reason on hover. Never an empty section. */
export function CountersUnavailable() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-5 gap-y-12 max-w-6xl w-full mx-auto text-center" data-counters="unavailable">
      {COUNTER_LABELS.map((row) => (
        <div key={row.key} className="min-w-0">
          <span title={UNAVAILABLE_TITLE} className="stat-number font-display font-bold text-primary tabular-nums block whitespace-nowrap">—</span>
          <p className={`font-mono text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-3 ${row.key === "contracts" ? "lg:whitespace-nowrap" : "whitespace-nowrap"}`}>{row.label}</p>
        </div>
      ))}
    </div>
  );
}
