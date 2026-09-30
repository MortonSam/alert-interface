// The home page's note block renders the most recently verified note's own figures. These helpers turn the
// note's stored stats and verification into the three facts and the one verification line it shows.

import type { LatestVerifiedNote, StructuredNoteStats } from "@/lib/api";

export const NO_VERIFIED_NOTE = "No verified research note is available right now. Notes appear here once a second model has checked them against the filing.";

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
  if (stats.eps_actual != null) {
    const sub = stats.eps_estimate != null
      ? `vs $${stats.eps_estimate.toFixed(2)} est${stats.eps_beat_pct != null ? ` \u00B7 ${stats.eps_beat_pct > 0 ? "+" : ""}${stats.eps_beat_pct.toFixed(1)}%` : ""}`
      : undefined;
    out.push({ label: "EPS", value: `$${stats.eps_actual.toFixed(2)}`, sub });
  }
  if (stats.beat_count != null && stats.total_quarters != null) out.push({ label: "EPS beats", value: `${stats.beat_count}/${stats.total_quarters}`, sub: "quarters" });
  if (stats.latest_move_1d != null) out.push({ label: "Latest move", value: stats.latest_move_1d, sub: `post-earnings 1d${stats.latest_outcome ? ` \u00B7 ${stats.latest_outcome}` : ""}` });
  return out.slice(0, 3);
}

/** "13 claims checked: 12 supported, 1 unsupported, 0 contradicted" */
export function verificationLine(v: LatestVerifiedNote["verification_summary"]): string | null {
  if (!v) return null;
  const total = v.supported + v.unsupported + v.contradicted;
  return `${total} claims checked: ${v.supported} supported, ${v.unsupported} unsupported, ${v.contradicted} contradicted`;
}
