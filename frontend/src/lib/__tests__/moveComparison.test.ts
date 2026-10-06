import { describe, expect, it } from "vitest";
import { comparisonParts } from "@/lib/moveComparison";
import GLOSSARY from "@/lib/glossary";

describe("the calendar's options-against-typical line", () => {
  it("links the implied move and the typical move once each and keeps the API's words", () => {
    const item = { comparison: "Options price a ±6.0% move; it has moved ±4.0% on a typical report, more than usual (chain Oct 5, 2026).", implied_move_pct: 6.0, typical_move_pct: 4.0 };
    const parts = comparisonParts(item)!;
    expect(parts.map((p) => p.text).join("")).toBe(item.comparison);
    expect(parts.filter((p) => p.term).map((p) => [p.text, p.term])).toEqual([["±6.0% move", "implied move"], ["±4.0% on a typical report", "typical move"]]);
    expect(GLOSSARY["typical move"]).toMatch(/\. .+\.$/);
    expect(comparisonParts({ comparison: null, implied_move_pct: null, typical_move_pct: null })).toBeNull();     // no comparison, no line
  });
});
