"use client";

// Disclosures sentences that depend on Ivy's rule, the ledger flag
// or real database counts. They render from the API; nothing here is a typed number.

import { fmtLongDate, ledgerVisibilityClause } from "@/lib/ivyRule";
import { useIvyRule } from "@/lib/useIvyRule";

export function LedgerStartDate({ fallback = "its start date" }: { fallback?: string }) {
  const ivy = useIvyRule();
  return <>{ivy ? fmtLongDate(ivy.rule.ledger_start) : fallback}</>;
}

/** The disclosures' clause on who sees the picks, from the flag. Before the rule loads it makes no claim. */
export function LedgerVisibilityClause() {
  const ivy = useIvyRule();
  return <>{ivy ? ledgerVisibilityClause(ivy.rule) : "and are recorded nightly"}</>;
}

