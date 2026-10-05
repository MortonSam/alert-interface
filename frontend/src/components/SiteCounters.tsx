"use client";

import { useEffect, useState } from "react";
import { api, type SiteStats } from "@/lib/api";
import { CountUp } from "@/components/CountUp";
import { counterRows } from "@/lib/siteCounters";

/** Four counts from /system/stats in one compact row. The number carries the weight, the label sits under it, and
 * the date each count rests on is the number's hover title. Renders nothing until the counts arrive and nothing at
 * all when the API cannot be reached. */
export function SiteCounters() {
  const [stats, setStats] = useState<SiteStats | null>(null);
  useEffect(() => {
    api.system.stats().then(setStats).catch(() => {});
  }, []);
  const rows = counterRows(stats);
  if (!rows.length) return null;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-8 md:gap-6 max-w-3xl w-full mx-auto text-center">
      {rows.map((row) => (
        <div key={row.key}>
          <CountUp value={row.value} title={row.asOf ?? undefined} className="font-display font-bold text-foreground block whitespace-nowrap text-4xl sm:text-5xl tracking-[-.02em]" />
          <p className="font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground mt-2">{row.label}</p>
        </div>
      ))}
    </div>
  );
}
