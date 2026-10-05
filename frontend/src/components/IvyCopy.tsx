"use client";

// Homepage and disclosures sentences that depend on Ivy's rule, the ledger flag
// or real database counts. They render from the API; nothing here is a typed number.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtLongDate, ledgerRecordSentence, ledgerVisibilityClause, scoreKeepingPhrase } from "@/lib/ivyRule";
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
