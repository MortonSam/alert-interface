"use client";

import { useEffect, useState } from "react";
import { api, type HealthStatus, type SystemStatus } from "@/lib/api";

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

export default function MeetIvyPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    Promise.all([api.system.health(), api.system.status()])
      .then(([h, s]) => {
        setHealth(h);
        setStatus(s);
      })
      .catch(() => setError(true));
  }, []);

  const loading = !health && !status && !error;

  return (
    <div className="space-y-10 pb-10">
      {/* Section 1 — Who she is */}
      <section>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Who she is
        </p>
        <h2 className="font-display text-lg font-bold mt-1">
          The analyst inside Alert Interface
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed mt-2">
          Ivy reads earnings history, live options data, and analyst moves for
          every ticker she tracks. She synthesizes the numbers into a direction,
          picks a strategy, and shows her reasoning on every call.
        </p>
      </section>

      {/* Section 2 — How she decides */}
      <section>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          How she decides
        </p>
        <h2 className="font-display text-lg font-bold mt-1">
          Grounded in data she can verify
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed mt-2">
          Every pick gets a thesis, an entry mark, and a permanent score against
          the market. She weighs earnings surprise rates, historical move
          magnitudes, and the options-implied expected move before committing to a
          direction.
        </p>
      </section>

      {/* Section 3 — What she won't do */}
      <section>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          What she won&apos;t do
        </p>
        <h2 className="font-display text-lg font-bold mt-1">
          No pick without a clear signal
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed mt-2">
          She won&apos;t force a direction when the data is mixed. One pick per
          symbol, no stacking. And she never quietly edits her record; every
          call stays on the ledger exactly as she made it.
        </p>
      </section>

      {/* Section 4 — Right now */}
      <section>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Right now
        </p>
        <h2 className="font-display text-lg font-bold mt-1">
          Always working
        </h2>

        {loading && (
          <div className="mt-3 space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-4 w-48 animate-pulse rounded bg-muted"
              />
            ))}
          </div>
        )}

        {!loading && !error && (
          <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
            {health?.refresh_in_progress && (
              <li className="animate-pulse">Refreshing data…</li>
            )}
            {!health?.refresh_in_progress && health?.last_refreshed_at && (
              <li>Data refreshed {timeAgo(health.last_refreshed_at)}</li>
            )}
            {status?.total_tickers != null && (
              <li>{status.total_tickers} tickers tracked</li>
            )}
            {status?.total_reactions != null && (
              <li>{status.total_reactions} earnings reactions scanned</li>
            )}
            {status?.most_recent_reaction_date && (
              <li>Latest reaction {status.most_recent_reaction_date}</li>
            )}
            {health?.rv_latest_date && (
              <li>RV snapshot {health.rv_latest_date}</li>
            )}
          </ul>
        )}
      </section>
    </div>
  );
}
