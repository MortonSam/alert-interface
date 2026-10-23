import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { ROW_LABELS, TRADING_DAYS_PER_YEAR, dailyPct, ivRowValue, rvRowValue, spreadRowValue } from "@/lib/optionsRows";
import { SPREAD_CHEAP_PP, SPREAD_RICH_PP } from "@/lib/thresholds";
import GLOSSARY from "@/lib/glossary";

describe("Options Details rows in plain words (Sam, 2026-10-22)", () => {
  it("IV and RV, verbatim, with the typical day from annual / sqrt(252)", () => {
    expect(TRADING_DAYS_PER_YEAR).toBe(252);
    expect(dailyPct(0.412)).toBe("2.6");
    expect(dailyPct(0.38)).toBe("2.4");
    expect(ivRowValue(0.412, "Oct 19, 2026")).toBe(
      "41.2% a year, about 2.6% on a typical day, from the options nearest today's price that end at least 7 days out (as of Oct 19, 2026)");
    expect(rvRowValue(0.38, 20, "Oct 19, 2026")).toBe(
      "38.0% a year, about 2.4% on a typical day, from its daily moves over the last 20 trading days (as of Oct 19, 2026)");
  });
  it("the spread's three wordings follow the thresholds", () => {
    expect(spreadRowValue(SPREAD_RICH_PP + 3.2)).toBe(`Options expect ${(SPREAD_RICH_PP + 3.2).toFixed(1)} points more swing than the stock has shown lately, so they look pricey`);
    expect(spreadRowValue(SPREAD_CHEAP_PP - 3.2)).toBe(`Options expect ${(-(SPREAD_CHEAP_PP - 3.2)).toFixed(1)} points less swing than the stock has shown lately, so they look cheap`);
    for (const x of [3.2, SPREAD_RICH_PP, SPREAD_CHEAP_PP, 0, -3.2]) expect(spreadRowValue(x)).toBe("Options expect about the same swing the stock has shown lately");
  });
  it("no colons, pp, ≥ or monospace in the rows", () => {
    const texts = [...Object.values(ROW_LABELS), ivRowValue(0.412, "Oct 19, 2026"), rvRowValue(0.38, 20, null), spreadRowValue(20), spreadRowValue(-20), spreadRowValue(0)];
    for (const t of texts) expect(t).not.toMatch(/:|\bpp\b|≥/);
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    for (const id of ["iv-row", "rv-row", "spread-row"]) {
      const at = page.indexOf(`data-testid="${id}"`);
      expect(at).toBeGreaterThan(0);
      const row = page.slice(page.lastIndexOf("<div", at), page.indexOf("</div>", at));
      expect(row).not.toMatch(/font-mono|tabular-nums/);
    }
    expect(page).not.toContain("IV - RV spread</ExplainTip>");
  });
  it("each term has one plain sentence in the glossary", () => {
    for (const k of ["iv", "rv", "iv/rv spread", "rv rank"]) {
      const g = GLOSSARY[k];
      expect(g.split(/(?<=\.)\s/).length).toBe(1);
      expect(g).not.toMatch(/\b(IV|RV|volatility|pp)\b/);
    }
  });
});
