import { describe, expect, it } from "vitest";
import { cardEarningsNote, checkedPhrase, earningsSourceNote, nextEarningsLine, noDateLine } from "@/lib/earningsSource";

const NOW = new Date(2026, 8, 29, 10, 30);   // Sep 29, 2026, local

describe("next earnings line", () => {
  it("prints the date, the source and when the source was last asked", () => {
    expect(nextEarningsLine("2026-10-29", "finnhub", "2026-09-29T06:05:00Z", NOW)).toBe("Next earnings Oct 29 (Finnhub, checked today)");
    expect(nextEarningsLine("2026-10-28", "yfinance", "2026-09-26T05:23:16Z", NOW)).toBe("Next earnings Oct 28 (Yahoo Finance, checked 3 days ago)");
  });
  it("a missing date still says when it was checked, and an unchecked ticker says so", () => {
    expect(nextEarningsLine(null, null, "2026-09-29T06:05:00Z", NOW)).toBe("No confirmed date yet (Finnhub, checked Sep 29)");
    expect(nextEarningsLine(null, null, null, NOW)).toBe("No confirmed date yet (not yet checked)");
    expect(nextEarningsLine("2026-12-09", "finnhub", null, NOW)).toBe("Next earnings Dec 9 (Finnhub, not yet checked)");
  });
  it("checked phrases are calendar days, not 24-hour windows", () => {
    expect(checkedPhrase("2026-09-28T23:59:00", NOW)).toBe("checked yesterday");
    expect(checkedPhrase("2026-09-29T00:01:00", NOW)).toBe("checked today");
    expect(checkedPhrase("garbage", NOW)).toBe("not yet checked");
  });
  it("the Discover note is the short form", () => {
    expect(earningsSourceNote("finnhub", "2026-09-29T06:05:00Z", NOW)).toBe("Finnhub, checked today");
    expect(earningsSourceNote(null, null, NOW)).toBe("not yet checked");
  });
});

describe("a ticker the calendar left without a date is never blank", () => {
  it("says so with the source and the check date, everywhere the date would show", () => {
    expect(noDateLine("2026-09-28T06:05:00Z")).toBe("No confirmed date yet (Finnhub, checked Sep 28)");
    expect(cardEarningsNote(null, null, "2026-09-29T06:05:00Z", NOW)).toBe("No confirmed date yet (Finnhub, checked Sep 29)");
    expect(cardEarningsNote("2026-10-29", "finnhub", "2026-09-29T06:05:00Z", NOW)).toBe("Next earnings Oct 29 \u00B7 Finnhub, checked today");
  });
  it("the ticker grid, Build fact grid and Discover cards render the no-date line from the API fields", () => {
    const { readFileSync } = require("node:fs") as typeof import("node:fs");
    const { join } = require("node:path") as typeof import("node:path");
    const src = join(__dirname, "../..");
    const grid = readFileSync(join(src, "app/ticker-grid.tsx"), "utf8");
    expect(grid).toMatch(/noDateLine\(ticker\.next_earnings_checked_at\)/);
    expect(grid).not.toMatch(/\{ticker\.next_earnings_date && \(/);
    const build = readFileSync(join(src, "app/build/page.tsx"), "utf8");
    expect(build).toMatch(/fb\.earnings_date \?\? noDateLine\(fb\.earnings_checked_at\)/);
    expect(build).not.toContain('fb.earnings_date ?? "n/a"');
    const discover = readFileSync(join(src, "app/discover/page.tsx"), "utf8");
    expect((discover.match(/cardEarningsNote\(item\.earnings_date, item\.earnings_source, item\.earnings_checked_at\)/g) || []).length).toBe(2);
  });
});
