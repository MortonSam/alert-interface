import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { IVY_PAGE } from "@/lib/ivyPageCopy";
import { PUBLIC_PATHS } from "@/app/sitemap";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

const lines = (): string[] => [
  IVY_PAGE.headline, IVY_PAGE.searchLabel, IVY_PAGE.searchPlaceholder, IVY_PAGE.quickPicks, IVY_PAGE.noWalkthrough("NVIDIA"),
  IVY_PAGE.stepFrom("NVIDIA"), IVY_PAGE.startWalk("NVIDIA"), IVY_PAGE.checkTitle, IVY_PAGE.noteFrom("NVIDIA Corporation"),
  IVY_PAGE.filingFrom("10-Q", "Aug 26, 2026"), IVY_PAGE.readFiling, IVY_PAGE.checked("398", "Nov 2, 2026"), IVY_PAGE.ideasTitle, IVY_PAGE.closing,
];

describe("the one Ivy page (Sam, 2026-11-02)", () => {
  it("says what Sam wrote, and no line has a colon, a dash, a pick or advice", () => {
    expect(IVY_PAGE.headline).toBe("Ivy reads the filings, so you understand the company.");
    expect(IVY_PAGE.closing).toBe("Ivy doesn't tell you what to buy or sell. She shows you how to decide for yourself.");
    for (const l of lines()) {
      expect(l, l).not.toMatch(/[:—–]/);
      expect(l, l).not.toMatch(/\b(?:picks?|ledger|backtest|setup|track record|win rate|you should|buy now|sell now)\b/i);
    }
  });

  it("types no count or date: they come from the API with their own dates", () => {
    const page = read("app/ivy/page.tsx");
    expect(page).toContain("fetchIvyPage()");
    expect(page).toContain("C.checked(page.trust.checked.count");
    expect(page).not.toMatch(/(?<![-\w])(?:300|398|452|503)\b/);         // no count typed by hand
    expect(page).toMatch(/walkHref\(idea\.symbol, idea\.n\)/);           // each idea opens its example step
    expect(page).toContain("<StepScreen step={step} w={walk}");            // a real step, rendered by the walkthrough's own component
    expect(page).not.toMatch(/cards|ivy-trust|Ivy's Read/);                // no descriptive boxes (Sam, 2026-11-03)
  });

  it("the old pages redirect to /ivy and leave the sitemap, the nav and every page", () => {
    for (const p of ["app/ivy/desk/page.tsx", "app/ivy/trades/page.tsx", "app/ivy/picks/page.tsx", "app/alerts-trades/page.tsx"]) {
      expect(read(p), p).toContain('permanentRedirect("/ivy")');
    }
    expect(PUBLIC_PATHS).toContain("/ivy");
    expect(PUBLIC_PATHS.filter((p) => p.startsWith("/ivy/"))).toEqual([]);
    expect(read("app/ivy/layout.tsx")).not.toMatch(/\/ivy\/(?:desk|trades)|<nav/);
    for (const p of ["app/page.tsx", "app/discover/page.tsx", "app/disclosures/page.tsx", "app/build/page.tsx", "components/NavLinks.tsx"]) {
      expect(read(p), p).not.toMatch(/\/ivy\/(?:desk|trades|picks)|Ivy's Desk|Ivy's Trades|From the ledger/);
    }
  });
});
