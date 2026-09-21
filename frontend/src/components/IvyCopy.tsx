"use client";

// Homepage and disclosures sentences that depend on Ivy's rule, the ledger flag
// or real database counts. They render from the API; nothing here is a typed number.

import { useEffect, useState } from "react";
import { api, type SiteStats } from "@/lib/api";
import { CountUp } from "@/components/CountUp";
import { fmtLongDate, ledgerRecordSentence, scoreKeepingPhrase } from "@/lib/ivyRule";
import { useIvyRule } from "@/lib/useIvyRule";

export function LedgerStartDate({ fallback = "its start date" }: { fallback?: string }) {
  const ivy = useIvyRule();
  return <>{ivy ? fmtLongDate(ivy.rule.ledger_start) : fallback}</>;
}

export function HomeLedgerHeadline() {
  const ivy = useIvyRule();
  return <>Then Ivy makes the call, and {ivy ? scoreKeepingPhrase(ivy.rule) : "keeps score"}.</>;
}

export function HomeLedgerBody() {
  const ivy = useIvyRule();
  return <>{ivy ? ledgerRecordSentence(ivy.rule) : ""} Her losses sit right next to her wins.</>;
}

export function HomeLedgerFootnote() {
  const ivy = useIvyRule();
  if (!ivy) return <>Hypothetical picks, never executed.</>;
  return <>{ivy.rule.ledger_public ? "Hypothetical picks, published for everyone, never executed." : "Hypothetical picks, never executed. Published for everyone at launch."}</>;
}

/** The homepage counters, from real counts. Hidden until the counts arrive. */
export function SiteCounters() {
  const [stats, setStats] = useState<SiteStats | null>(null);
  useEffect(() => {
    api.system.stats().then(setStats).catch(() => {});
  }, []);
  if (!stats) return <div className="min-h-[8rem]" aria-hidden />;

  const since = stats.analyst_actions_since ? stats.analyst_actions_since.slice(0, 4) : null;
  const counters = [
    { value: stats.earnings_reports_measured, label: "Earnings reactions measured" },
    { value: stats.analyst_actions, label: since ? `Analyst actions since ${since}` : "Analyst actions" },
  ];
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-16 md:gap-12 max-w-[1100px] w-full mx-auto text-center">
      {counters.map((stat) => (
        <div key={stat.label}>
          <CountUp
            value={stat.value}
            className="stat-number font-display font-bold text-foreground block whitespace-nowrap"
          />
          <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground mt-3">{stat.label}</p>
        </div>
      ))}
    </div>
  );
}
