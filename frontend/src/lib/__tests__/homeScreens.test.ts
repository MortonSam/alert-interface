import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fitPageSize } from "@/app/ticker-grid";

// Every home section is exactly one screen with its content centered (Sam, 2026-11-02): a section scrolled to fills the screen
// alone. Checked in real Chrome and WebKit at 390, 1440 and 1170 (scratchpad homesections.mjs); these hold the rules in source.
const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("the market grid's page holds what fits", () => {
  it("whole rows only, at least one, columns from the grid", () => {
    expect(fitPageSize(400, 6, 185)).toBe(12);          // (400 + 12) / (185 + 12) = 2 rows of 6
    expect(fitPageSize(196, 6, 185)).toBe(6);           // just under two rows: one
    expect(fitPageSize(50, 2, 185)).toBe(2);            // too little room: one row, never none
    expect(fitPageSize(800, 0, 185)).toBe(4);           // no template read yet: one column
  });
});

describe("one screen per home section", () => {
  it("every top-level home section is a screen section, and the market grid is held to exactly one from 640px up", () => {
    const home = read("app/page.tsx");
    const sections = [...home.matchAll(/<section(?: id="[^"]*")? className="([^"]*)"/g)].map((m) => m[1]);
    expect(sections.length).toBeGreaterThanOrEqual(8);
    for (const c of sections) expect(c, c).toMatch(/\bscreen-section\b/);
    expect(home).toMatch(/id="market" className="screen-section screen-fit flex flex-col/);
    expect(home).toContain('className="screen-section flex flex-col justify-center"');      // the latest verified note
    const css = read("app/globals.css");
    expect(css).toMatch(/^@media \(min-width: 640px\) \{ main \.screen-fit \{ height: calc\(100svh - 3\.25rem - 1px\); \} \}$/m);
    const grid = read("app/ticker-grid.tsx");
    expect(grid).toContain("fitPageSize(box.clientHeight, cols, rowH)");
    expect(grid).toContain('className="sm:flex-1 sm:min-h-0 sm:overflow-hidden flex flex-col sm:justify-center"');
  });

  it("on a phone the market section grows with a page of whole cards, and the Ivy section ends at its button (Sam, 2026-11-10)", async () => {
    const { PHONE_PAGE_SIZE } = await import("@/app/ticker-grid");
    expect(PHONE_PAGE_SIZE).toBe(10);
    const grid = read("app/ticker-grid.tsx");
    expect(grid).toContain("window.matchMedia(PHONE_QUERY).matches");
    expect(grid).toContain('"text-xs text-muted-foreground sm:line-clamp-2 leading-snug"');     // a phone card's name is never cut
    expect(grid).toContain('"sm:mt-auto pt-1 space-y-0.5"');                                    // no gap between name and sector
    expect(grid).not.toMatch(/datasetAgeLine|freshnessLine\(/);                                    // the status line: the price note alone
    expect(grid).toContain("{hasCaps && <option value=\"market_cap\">");                        // no sort named for a value not shown
    const css = read("app/globals.css");
    expect(css).toContain("main .screen-section.ivy-home-section { min-height: 0; padding-top: max(3rem, calc((100svh - 3.25rem - 1px - 25.5rem) / 2)); padding-bottom: 0; }");
  });

  it("the opening keeps its cue at the bottom of its own screen, and the header hides what scrolls under it", () => {
    const home = read("app/page.tsx");
    expect(home).toMatch(/className="open-cue absolute inset-x-0 bottom-0[^"]*"/);
    expect(read("app/layout.tsx")).toContain('<header className="border-b bg-background sticky top-0 z-40">');   // opaque, no blur
  });
});

describe("status lines (Sam, 2026-11-10)", () => {
  it("no page shows a dataset's age or a refresh step's state to a visitor: the price delay note alone", () => {
    for (const p of ["app/discover/page.tsx", "app/ivy/layout.tsx", "components/ivy/IvyFrame.tsx", "app/ivy/page.tsx", "app/tickers/[symbol]/page.tsx", "app/watchlist/page.tsx", "app/ticker-grid.tsx"]) {
      const src = read(p);
      expect(src, p).not.toMatch(/datasetAgeLine\(|freshnessLine\(|Data refreshed|refreshing her data/);
    }
  });
});
