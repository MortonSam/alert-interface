import { computedHowLine, insightAsOfLine } from "@/lib/insightHeadline";

/**
 * The overview headline as the ticker page renders it: the stored insight sentence, how it was computed, and the
 * date of the stat it rests on. The same component serves the ticker page and the home page's "from a real stock
 * page" block, so the two can never drift apart.
 */
export function InsightHeadline({ insight, rule, asOf }: { insight: string; rule: string | null; asOf: string | null }) {
  const how = computedHowLine(rule);
  const asOfLine = insightAsOfLine(asOf);
  return (
    <>
      <p className="text-2xl font-display text-foreground/80 leading-relaxed">{insight}</p>
      {how && <p className="text-xs text-muted-foreground mt-1.5">{how}</p>}
      {asOfLine && <p className="text-xs text-muted-foreground/70 mt-1">{asOfLine}</p>}
    </>
  );
}
