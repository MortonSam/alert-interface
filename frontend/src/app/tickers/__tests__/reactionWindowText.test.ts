import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { ANALYST_WINDOW_TEXT, REACTION_WINDOW_TEXT, fedVsEarningsLine } from "../[symbol]/reactionWindowText";
import GLOSSARY from "../../../lib/glossary";

const page = readFileSync(join(__dirname, "../[symbol]/page.tsx"), "utf8");

describe("reaction window wording matches what is computed", () => {
  it("Fed mode never talks about a report or BMO/AMC", () => {
    const fed = REACTION_WINDOW_TEXT.fed;
    for (const text of [fed.tooltip1d, fed.tooltip5d, fed.footnote, fed.basis]) {
      expect(text.toLowerCase()).not.toContain("report");
      expect(text).not.toMatch(/BMO|AMC/);
    }
    expect(fed.footnote).toContain("open(T)");
  });

  it("earnings mode states the timing-aware close-to-close windows", () => {
    expect(REACTION_WINDOW_TEXT.earnings.footnote).toContain("BMO: close(T-1)");
    expect(REACTION_WINDOW_TEXT.earnings.footnote).toContain("AMC: close(T)");
  });

  it("every column tooltip term exists in the glossary", () => {
    for (const mode of ["earnings", "fed"] as const)
      for (const term of Object.values(REACTION_WINDOW_TEXT[mode].glossaryTerm))
        expect(Object.keys(GLOSSARY), term).toContain(term);
    expect(Object.keys(GLOSSARY)).toContain("median event-day move");
  });

  it("the Fed versus earnings line names both bases", () => {
    const line = fedVsEarningsLine(1.2, 4.8);
    expect(line).toContain(REACTION_WINDOW_TEXT.fed.basis);
    expect(line).toContain(REACTION_WINDOW_TEXT.earnings.basis);
  });

  it("analyst wording says event day and 2-4 sessions, never next-day or a week", () => {
    expect(ANALYST_WINDOW_TEXT.day0).toBe("event-day move");
    expect(ANALYST_WINDOW_TEXT.later).toBe("2–4 sessions later");
    expect(page).not.toMatch(/next-day|next day|a week later/);
    expect(page).not.toContain(">Stopped<");
  });
});
