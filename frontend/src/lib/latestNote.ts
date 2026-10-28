// The home page's note block renders the most recently verified note's own figures. These helpers turn the
// note's stored stats and verification into the three facts and the one verification line it shows.

import type { LatestVerifiedNote, StructuredNoteStats } from "@/lib/api";
import { fmtDate } from "@/lib/dates";

/** A note written before its company reported again: "Written before the Sep 30 report" (the API's report_since, services/note_currency). */
export function writtenBeforeLabel(reportSince: string | null | undefined): string | null {
  if (!reportSince) return null;
  return `Written before the ${fmtDate(reportSince.slice(0, 10))} report`;
}

function fmtCap(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toFixed(0)}`;
}

export interface NoteFact { label: string; value: string; sub?: string }

/** Three facts from the note's own stats, in a fixed order, skipping any the note does not hold. */
export function noteFacts(stats: StructuredNoteStats | null): NoteFact[] {
  if (!stats) return [];
  const out: NoteFact[] = [];
  if (stats.market_cap != null) out.push({ label: "Market cap", value: fmtCap(stats.market_cap) });
  if (stats.eps_sec != null) out.push({ label: "EPS", value: `$${stats.eps_sec.toFixed(2)}` });   // SEC diluted EPS, as the note's text
  return out.slice(0, 3);
}

/** "12 claims confirmed against the filing": the served note keeps its confirmed claims only (backend services/note_claims). */
export function verificationLine(v: LatestVerifiedNote["verification_summary"]): string | null {
  if (!v || v.supported === 0) return null;
  return `${v.supported} claim${v.supported === 1 ? "" : "s"} confirmed against the filing`;
}
