import type { ReportingSoonItem } from "@/lib/api";

export interface LinePart { text: string; term?: string }

/** The API's comparison sentence split so that the report move ("a move of about 6.0% from the report itself") links the
 * report-move entry and the typical move ("the 4.0% it has moved on a typical report") links the typical-move entry. A sentence
 * saying the options give no report move comes through whole. Null when the API sent no sentence. Pure. */
export function comparisonParts(item: Pick<ReportingSoonItem, "comparison" | "report_move_pct" | "typical_move_pct">): LinePart[] | null {
  const text = item.comparison;
  if (!text) return null;
  const phrases: [string, string][] = [];
  if (item.report_move_pct != null) phrases.push([`a move of about ${item.report_move_pct.toFixed(1)}% from the report itself`, "report move"]);
  if (item.typical_move_pct != null) phrases.push([`the ${item.typical_move_pct.toFixed(1)}% it has moved on a typical report`, "typical move"]);
  const out: LinePart[] = [];
  let cursor = 0;
  for (const [phrase, term] of phrases) {
    const idx = text.indexOf(phrase, cursor);
    if (idx < 0) continue;
    if (idx > cursor) out.push({ text: text.slice(cursor, idx) });
    out.push({ text: phrase, term });
    cursor = idx + phrase.length;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) });
  return out;
}
