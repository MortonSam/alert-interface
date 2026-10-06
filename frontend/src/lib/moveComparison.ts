import type { ReportingSoonItem } from "@/lib/api";

export interface LinePart { text: string; term?: string }

/** The API's comparison sentence split so that the implied move ("±6.0% move") links the implied-move entry and the typical
 * move ("±4.0% on a typical report") links the typical-move entry. Null when the API sent no comparison. Pure. */
export function comparisonParts(item: Pick<ReportingSoonItem, "comparison" | "implied_move_pct" | "typical_move_pct">): LinePart[] | null {
  const text = item.comparison;
  if (!text || item.implied_move_pct == null || item.typical_move_pct == null) return null;
  const implied = `±${item.implied_move_pct.toFixed(1)}% move`;
  const typical = `±${item.typical_move_pct.toFixed(1)}% on a typical report`;
  const out: LinePart[] = [];
  let cursor = 0;
  for (const [phrase, term] of [[implied, "implied move"], [typical, "typical move"]] as const) {
    const idx = text.indexOf(phrase, cursor);
    if (idx < 0) continue;
    if (idx > cursor) out.push({ text: text.slice(cursor, idx) });
    out.push({ text: phrase, term });
    cursor = idx + phrase.length;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) });
  return out;
}
