import { describe, expect, it } from "vitest";
import { yearLabel, yearTicks } from "@/lib/chartAxis";

describe("5Y chart axis", () => {
  it("ticks January 1 of each year inside the five years, labelled by year", () => {
    const ticks = yearTicks(Date.parse("2021-10-15"), Date.parse("2026-10-15"));
    expect(ticks.map(yearLabel)).toEqual(["2022", "2023", "2024", "2025", "2026"]);
    expect(ticks.every((t) => new Date(t).getUTCMonth() === 0 && new Date(t).getUTCDate() === 1)).toBe(true);
  });
  it("adds no tick outside the data", () => {
    expect(yearTicks(Date.parse("2026-01-02"), Date.parse("2026-10-15"))).toEqual([]);
    expect(yearTicks(Date.parse("2025-12-31"), Date.parse("2026-01-01")).map(yearLabel)).toEqual(["2026"]);
  });
});
