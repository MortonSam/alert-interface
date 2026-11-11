import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { ROW_LABELS, TRADING_DAYS_PER_YEAR, dailyPct, ivRowValue, rankRowValue, rvRowValue, spreadChipValue, spreadRowValue } from "@/lib/optionsRows";
import { explanationOf } from "@/lib/glossary";
import { RV_RANK_ELEVATED, RV_RANK_EXTREME, RV_RANK_NORMAL } from "@/lib/thresholds";
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
    // the two yearly figures the rows above show, in whole numbers, never their difference in "points" (Sam, 2026-11-11)
    const rich = 0.3 + (SPREAD_RICH_PP + 3.2) / 100, cheap = 0.3 + (SPREAD_CHEAP_PP - 3.2) / 100;
    expect(spreadRowValue(SPREAD_RICH_PP + 3.2, rich, 0.3)).toBe(`Options expect swings of about ${Math.round(rich * 100)}% a year, more than the 30% the stock has shown lately, so they look pricey`);
    expect(spreadRowValue(SPREAD_CHEAP_PP - 3.2, cheap, 0.3)).toBe(`Options expect swings of about ${Math.round(cheap * 100)}% a year, less than the 30% the stock has shown lately, so they look cheap`);
    for (const x of [3.2, SPREAD_RICH_PP, SPREAD_CHEAP_PP, 0, -3.2]) expect(spreadRowValue(x, 0.3 + x / 100, 0.3)).toBe(
      `Options expect swings of about ${Math.round(30 + x)}% a year against the 30% the stock has shown lately, so they look neither pricey nor cheap`);
    expect(spreadRowValue(19.7, 0.477, 0.28)).toBe("Options expect swings of about 48% a year, more than the 28% the stock has shown lately, so they look pricey");
    for (const t of [spreadRowValue(19.7, 0.477, 0.28), spreadRowValue(-13.2, 0.4804, 0.6124), spreadRowValue(8.7, 0.579, 0.492)]) expect(t).not.toMatch(/\d\.\d/);
    // without both figures, the direction alone
    expect(spreadRowValue(SPREAD_RICH_PP + 3.2)).toBe("Options expect more swing than the stock has shown lately, so they look pricey");
    expect(spreadRowValue(SPREAD_CHEAP_PP - 3.2, null, 0.3)).toBe("Options expect less swing than the stock has shown lately, so they look cheap");
    expect(spreadRowValue(3.2, 0.332, null)).toBe("Options expect about the same swing the stock has shown lately");
  });
  it("Build a Trade's chip and the glossary line say the same thing with no points, pp or colon (Sam, 2026-11-11)", () => {
    expect(spreadChipValue(47.7, 28.0)).toBe("48% a year expected, 28% shown lately");
    const hover = explanationOf("iv/rv spread", false)!;
    expect(explanationOf("IV-RV spread", true)).toBe(hover);
    for (const t of [spreadChipValue(47.7, 28.0), hover]) expect(t).not.toMatch(/:|\bpp\b|\bpoints?\b/);
    expect(hover.match(/for example/g)?.length).toBe(1);
    const build = readFileSync(join(__dirname, "../../app/build/page.tsx"), "utf8");
    expect(build).toContain("spreadChipValue(fb.atm_iv_pct, fb.rv_20d_pct)");
    expect(build).not.toMatch(/toFixed\(1\)\}pp/);
  });
  it("the RV rank row, verbatim, from the percentile of days with its band by the same cutoffs", () => {
    expect(ROW_LABELS.rank).toBe("Recent swings against its past year");
    expect(rankRowValue(62.4, "Oct 19, 2026")).toBe("It is swinging more than on 62% of days in the past year, which counts as normal (as of Oct 19, 2026)");
    // MRNA on 2026-10-22: rank 12.3 (quiet by the old reading) but percentile 73.0, more than on 73% of days
    expect(rankRowValue(73.0, null)).toBe("It is swinging more than on 73% of days in the past year, which counts as elevated");
    // rounded down, so the band always matches the figure shown
    expect(rankRowValue(RV_RANK_ELEVATED - 0.4, null)).toContain(`${RV_RANK_ELEVATED - 1}% of days in the past year, which counts as normal`);
    expect(rankRowValue(RV_RANK_EXTREME, null)).toContain("counts as extreme");
    expect(rankRowValue(RV_RANK_NORMAL - 1, null)).toContain("counts as quiet");
  });
  it("no colons, pp, ≥ or monospace in the rows", () => {
    const texts = [...Object.values(ROW_LABELS), ivRowValue(0.412, "Oct 19, 2026"), rvRowValue(0.38, 20, null), spreadRowValue(20, 0.5, 0.3), spreadRowValue(-20, 0.3, 0.5), spreadRowValue(0, 0.3, 0.3), spreadRowValue(20), spreadRowValue(-20), spreadRowValue(0), rankRowValue(62, "Oct 19, 2026")];
    for (const t of texts) expect(t).not.toMatch(/:|\bpp\b|≥|\bpoints?\b/);
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    for (const id of ["iv-row", "rv-row", "spread-row", "rank-row"]) {
      const at = page.indexOf(`data-testid="${id}"`);
      expect(at).toBeGreaterThan(0);
      const row = page.slice(page.lastIndexOf("<div", at), page.indexOf("</div>", at));
      expect(row).not.toMatch(/font-mono|tabular-nums/);
    }
    expect(page).not.toContain("IV - RV spread</ExplainTip>");
    expect(page).not.toContain("RV rank</ExplainTip>");
    expect(page).toContain("rankRowValue(rvPct,");
  });
  it("each term has one plain sentence in the glossary", () => {
    for (const k of ["iv", "rv", "iv/rv spread", "rv rank"]) {
      const g = GLOSSARY[k];
      expect(g.split(/(?<=\.)\s/).length).toBe(1);
      expect(g).not.toMatch(/\b(IV|RV|volatility|pp)\b/);
    }
  });
});

describe("every recent-swings display reads the percentile of days (2026-10-26)", () => {
  it("the watchlist and Build a Trade show the share of days and the row's band", async () => {
    const { recentSwings } = await import("@/lib/utils");
    expect(recentSwings(73.0)).toMatchObject({ figure: "73% of days", tag: "elevated" });
    expect(recentSwings(90.9)).toMatchObject({ figure: "90% of days", tag: "extreme" });
    expect(recentSwings(69.9).tag).toBe("normal");
    const src = (p: string) => readFileSync(join(__dirname, "../..", p), "utf8");
    expect(src("app/watchlist/page.tsx")).toContain("recentSwings(data.rv_percentile)");
    expect(src("app/build/page.tsx")).toContain("recentSwings(fb.rv_percentile)");
    expect(src("app/watchlist/page.tsx") + src("app/build/page.tsx")).not.toMatch(/rv_rank\.toFixed|Realized-vol rank/);
    expect(src("lib/discoverSentences.ts")).not.toMatch(/RV rank \$\{/);
  });
});
