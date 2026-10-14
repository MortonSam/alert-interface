"use client";
import Explained from "@/components/Explained";

import ExplainTip from "@/components/ticker/ExplainTip";
import type { ReportingSoonItem } from "@/lib/api";
import { comparisonParts } from "@/lib/moveComparison";

/** "Options price a move of about 6.0% from the report itself, more than the 4.0% it has moved on a typical report (options from Oct 5, 2026)", the API's own
 * sentence, with the report move and the typical move linked to their glossary entries. Nothing when the API built none. */
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
          <span key={i}><Explained text={p.text} /></span>
        ),
      )}
    </span>
  );
}
