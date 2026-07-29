"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type AlertPickLedgerItem } from "@/lib/api";

export function IvyCard() {
  const [openCount, setOpenCount] = useState<number | null>(null);
  const [avgUnrealized, setAvgUnrealized] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.theses
      .alertPicks()
      .then((picks: AlertPickLedgerItem[]) => {
        if (cancelled) return;
        const open = picks.filter((p) => p.status === "open");
        if (open.length === 0) return;
        setOpenCount(open.length);
        const withMove = open.filter((p) => p.unrealized_move_pct != null);
        if (withMove.length > 0) {
          const avg =
            withMove.reduce((s, p) => s + p.unrealized_move_pct!, 0) /
            withMove.length;
          setAvgUnrealized(avg);
        }
      })
      .catch((e) => {
        if (!cancelled) console.error("[IvyCard] failed to load picks:", e);
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="rounded-2xl border border-border bg-card/60 px-8 py-8">
      <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-2">
        Your AI analyst
      </p>
      <h3 className="font-display text-xl font-bold text-foreground">
        Meet Ivy
      </h3>
      <p className="text-sm text-muted-foreground leading-relaxed mt-2 max-w-lg">
        Ivy is the AI analyst inside Alert Interface. She reads earnings data,
        options flow, and analyst moves, then makes a call and stands behind it.
      </p>

      {openCount != null && (
        <p className="font-mono text-xs text-muted-foreground mt-4">
          {openCount} open pick{openCount !== 1 ? "s" : ""}
          {avgUnrealized != null && (
            <>
              {" · "}avg {avgUnrealized >= 0 ? "+" : ""}
              {avgUnrealized.toFixed(1)}% unrealized
            </>
          )}
        </p>
      )}

      <Link
        href="/ivy"
        className="inline-block mt-5 text-sm font-semibold text-primary hover:underline"
      >
        Meet Ivy →
      </Link>
    </div>
  );
}
