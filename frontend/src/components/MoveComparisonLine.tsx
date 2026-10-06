"use client";

import ExplainTip from "@/components/ticker/ExplainTip";
import type { ReportingSoonItem } from "@/lib/api";
import { comparisonParts } from "@/lib/moveComparison";

/** "Options price a ±6.0% move; it has moved ±4.0% on a typical report, more than usual (chain Oct 5, 2026)", the API's own
 * sentence, with the implied move and the typical move linked to their glossary entries. Nothing when the API built none. */
export function MoveComparisonLine({ item }: { item: ReportingSoonItem }) {
  const parts = comparisonParts(item);
  if (!parts) return null;
  return (
    <span>
      {parts.map((p, i) =>
        p.term ? (
          <ExplainTip key={i} term={p.term}>
            <span className="underline decoration-dotted underline-offset-4 cursor-help" onClick={(e) => e.preventDefault()}>{p.text}</span>
          </ExplainTip>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </span>
  );
}
