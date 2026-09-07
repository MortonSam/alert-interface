"use client";

import { useEffect, useState } from "react";
import { api, type AlertPickLedgerItem } from "@/lib/api";

export function IvyStatLine({ className = "" }: { className?: string }) {
  const [line, setLine] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.theses
      .alertPicks()
      .then((picks: AlertPickLedgerItem[]) => {
        if (cancelled) return;
        const open = picks.filter((p) => p.status === "open");
        if (open.length === 0) return;
        let text = `${open.length} open pick${open.length !== 1 ? "s" : ""}`;
        const withMove = open.filter((p) => p.unrealized_move_pct != null);
        if (withMove.length > 0) {
          const avg =
            withMove.reduce((s, p) => s + p.unrealized_move_pct!, 0) /
            withMove.length;
          text += ` \u00b7 avg ${avg >= 0 ? "+" : ""}${avg.toFixed(1)}% stock move`;
        }
        setLine(text);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!line) return null;
  return <p className={className}>{line}</p>;
}
