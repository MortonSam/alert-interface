import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");

describe("a held ticker's page shows plain price facts below the deal note", () => {
  it("reads the note from the ticker record", () => {
    expect(page).toContain("const dealNote = ticker?.deal_note ?? null;");
  });
  it("the Evidence section is the note alone: no tabs, no Earnings (0), no empty-history line", () => {
    const i = page.indexOf("{dealNote ? (");
    expect(i).toBeGreaterThan(page.indexOf('label="Evidence"'));
    expect(page.slice(i, i + 200)).toContain('data-testid="evidence-deal-note">{dealNote}</p>');
    expect(page.indexOf("Earnings ({reactions.length})")).toBeGreaterThan(i);
    expect(page.indexOf("No reaction history available for this ticker yet.")).toBeGreaterThan(i);
  });
  it("the options-data line and the analyst move statistics are hidden", () => {
    expect(page).toContain("{!dealNote && datasetAgeLine(health?.datasets, TICKER_DATASETS, timeAgo) && (");
    expect(page).toContain("{!dealNote && analystStats && (hasAnalystSignal(");
    expect(page).toContain("{!dealNote && analystInsight && (");
    expect(page).toContain("if (dealNote || !analystDetail || !analystStats) return null;");
  });
});
