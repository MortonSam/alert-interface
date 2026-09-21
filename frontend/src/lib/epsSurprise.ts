// How an EPS surprise is shown. The backend decides the mode (thresholds.eps_surprise);
// this only formats it. Dollars when the estimate is near zero, a capped percent otherwise.
import { EPS_SURPRISE_PCT_CAP } from "@/lib/thresholds";

export interface EpsSurpriseFields {
  eps_surprise_pct: number | null;
  eps_surprise_dollars?: number | null;
  eps_surprise_display_pct?: number | null;
  eps_surprise_capped?: boolean;
  eps_estimate?: string | number | null;
  eps_actual?: string | number | null;
}

const money = (d: number) => `${d >= 0 ? "+" : "-"}$${Math.abs(d).toFixed(2)}`;

/** { text, title } for the surprise cell; null when there is nothing to show. */
export function fmtEpsSurprise(r: EpsSurpriseFields): { text: string; title: string } | null {
  const dollars = r.eps_surprise_dollars ?? null;
  const vs = r.eps_estimate != null && r.eps_actual != null
    ? `actual $${Number(r.eps_actual).toFixed(2)} vs estimate $${Number(r.eps_estimate).toFixed(2)}` : "";

  if (r.eps_surprise_pct == null) {
    if (dollars == null) return null;
    return { text: `${money(dollars)} vs est.`, title: `Estimate is near zero, so the surprise is shown in dollars. ${vs}`.trim() };
  }
  const shown = r.eps_surprise_display_pct ?? Math.max(-EPS_SURPRISE_PCT_CAP, Math.min(EPS_SURPRISE_PCT_CAP, r.eps_surprise_pct));
  const capped = r.eps_surprise_capped ?? Math.abs(r.eps_surprise_pct) > EPS_SURPRISE_PCT_CAP;
  const text = capped ? `${shown > 0 ? ">+" : "<-"}${EPS_SURPRISE_PCT_CAP}%` : `${shown > 0 ? "+" : ""}${shown.toFixed(1)}%`;
  const title = capped && dollars != null
    ? `Exact surprise ${money(dollars)} (${r.eps_surprise_pct.toFixed(0)}%). ${vs}`.trim()
    : vs;
  return { text, title };
}
