/** The overview headline block's own lines, rendered from the API's insight response and nothing typed by hand. */
import { fmtDate } from "@/lib/dates";

export const COMPUTED_HOW_PREFIX = "How this was computed: ";

export interface InsightView {
  insight: string | null;
  rule: string | null;
  as_of: string | null;
}

/** "As of Sep 24, 2026" from the stat's own ISO date; null when the response carries none. */
export function insightAsOfLine(asOf: string | null | undefined): string | null {
  if (!asOf) return null;
  const on = fmtDate(asOf.slice(0, 10));
  return on ? `As of ${on}` : null;
}

export function computedHowLine(rule: string | null | undefined): string | null {
  return rule ? `${COMPUTED_HOW_PREFIX}${rule}` : null;
}

/** The home block renders only when the stored stat is there. */
export function hasInsight(view: InsightView | null | undefined): view is InsightView & { insight: string } {
  return !!view && typeof view.insight === "string" && view.insight.length > 0;
}
