import { describe, expect, it } from "vitest";
import { checkedPhrase, earningsSourceNote, nextEarningsLine } from "@/lib/earningsSource";

const NOW = new Date(2026, 8, 29, 10, 30);   // Sep 29, 2026, local

describe("next earnings line", () => {
  it("prints the date, the source and when the source was last asked", () => {
    expect(nextEarningsLine("2026-10-29", "finnhub", "2026-09-29T06:05:00Z", NOW)).toBe("Next earnings Oct 29 (Finnhub, checked today)");
    expect(nextEarningsLine("2026-10-28", "yfinance", "2026-09-26T05:23:16Z", NOW)).toBe("Next earnings Oct 28 (Yahoo Finance, checked 3 days ago)");
  });
  it("a missing date still says when it was checked, and an unchecked ticker says so", () => {
    expect(nextEarningsLine(null, null, "2026-09-29T06:05:00Z", NOW)).toBe("No next earnings date (checked today)");
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
