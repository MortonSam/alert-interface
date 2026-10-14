import { describe, expect, it } from "vitest";
import { comparisonParts } from "@/lib/moveComparison";
import GLOSSARY from "@/lib/glossary";

describe("the calendar's report-move line", () => {
  it("links the report move and the typical move once each and keeps the API's words", () => {
    const item = { comparison: "Options price a move of about 6.0% from the report itself, more than the 4.0% it has moved on a typical report (options from Oct 5, 2026).", report_move_pct: 6.0, typical_move_pct: 4.0 };
    const parts = comparisonParts(item)!;
    expect(parts.map((p) => p.text).join("")).toBe(item.comparison);
    expect(parts.filter((p) => p.term).map((p) => [p.text, p.term])).toEqual([
      ["a move of about 6.0% from the report itself", "report move"], ["the 4.0% it has moved on a typical report", "typical move"]]);
    expect(GLOSSARY["typical move"]).toMatch(/\. .+\.$/);
    expect(GLOSSARY["report move"]).toMatch(/\. .+\.$/);
    expect(comparisonParts({ comparison: null, report_move_pct: null, typical_move_pct: null })).toBeNull();     // no sentence, no line
  });
  it("passes a sentence saying the options give no report move through whole", () => {
    const text = "The options don't separate a report move, because no expiration ends before the report.";
    expect(comparisonParts({ comparison: text, report_move_pct: null, typical_move_pct: null })).toEqual([{ text }]);
  });
});
