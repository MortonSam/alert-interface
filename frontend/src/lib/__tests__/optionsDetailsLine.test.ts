import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { optionsDetailsLine } from "@/lib/optionsDetailsLine";

describe("Options Details' opening line", () => {
  it("is Sam's sentence, verbatim, from the total and report moves", () => {
    expect(optionsDetailsLine(0.092, "2026-11-20", 0.043, "ok")).toBe(
      "Options price a move of about 9.2% by Nov 20, 2026 in total. About 4.3% of that comes from the report itself; the rest is the stock's ordinary day-to-day swing.");
  });
  it("says only the total without a report move, and nothing without a total or its date", () => {
    expect(optionsDetailsLine(0.092, "2026-11-20", null, "no_pair")).toBe("Options price a move of about 9.2% by Nov 20, 2026 in total.");
    expect(optionsDetailsLine(null, "2026-11-20", 0.043, "ok")).toBeNull();
    expect(optionsDetailsLine(0.092, null, 0.043, "ok")).toBeNull();
  });
  it("opens Details, and the large total figure is gone", () => {
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    const details = page.slice(page.indexOf('<Fold label="Details"'));
    expect(details.slice(0, 1500)).toContain("optionsDetailsLine(");
    expect(page).not.toContain('text-6xl font-bold tabular-nums tracking-tight');
  });
});
