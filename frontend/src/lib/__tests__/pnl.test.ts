import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { averagePnlPct, fmtPnlPct } from "../pnl";

describe("P&L percent is a percent everywhere", () => {
  it("formats a percent without rescaling", () => {
    expect(fmtPnlPct(-35)).toBe("-35.0%");
    expect(fmtPnlPct(12.34)).toBe("+12.3%");
    expect(fmtPnlPct(-100)).toBe("-100.0%");
  });

  it("averages percents and ignores missing values", () => {
    expect(averagePnlPct([-35, -100, null, undefined])).toBe(-67.5);
    expect(averagePnlPct([])).toBeNull();
  });

  it("no page rescales a P&L percent, so a mixed-unit average cannot be produced client-side", () => {
    const pages = [
      "app/theses/page.tsx", "app/theses/[id]/page.tsx",
      "app/tickers/[symbol]/page.tsx", "app/ivy/trades/page.tsx", "app/discover/page.tsx",
    ];
    for (const p of pages) {
      const src = readFileSync(join(__dirname, "../..", p), "utf8");
      expect(src, p).not.toMatch(/pnl[A-Za-z_.?!]*\s*\*\s*100/i);
      expect(src, p).not.toMatch(/\(pct \* 100\)\.toFixed/);
    }
  });

  it("the trades page average comes from the shared helper", () => {
    const src = readFileSync(join(__dirname, "../../app/ivy/trades/page.tsx"), "utf8");
    expect(src).toContain("averagePnlPct(closedPicks.map((p) => p.option_pnl_pct))");
  });
});
