import { describe, it, expect } from "vitest";
import { chainDateLabel } from "../[symbol]/optionsReadFootnote";

describe("Ivy's Read chain date label", () => {
  it("uses the chain's own date", () => {
    expect(chainDateLabel({ chain_date: "2026-09-18" })).toBe(" · chain as of 2026-09-18");
  });
  it("is omitted when there is no chain date, and never falls back to today", () => {
    const today = new Date().toISOString().slice(0, 10);
    for (const read of [{ chain_date: null }, { chain_date: undefined }, {}]) {
      const label = chainDateLabel(read as { chain_date?: string | null });
      expect(label).toBe("");
      expect(label).not.toContain(today);
    }
  });
});
