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
  it("every top-level home section is a screen section, and the market grid is held to exactly one", () => {
    const home = read("app/page.tsx");
    const sections = [...home.matchAll(/<section(?: id="[^"]*")? className="([^"]*)"/g)].map((m) => m[1]);
    expect(sections.length).toBeGreaterThanOrEqual(8);
    for (const c of sections) expect(c, c).toMatch(/\bscreen-section\b/);
    expect(home).toMatch(/id="market" className="screen-section screen-fit flex flex-col/);
    expect(home).toContain('className="screen-section flex flex-col justify-center"');      // the latest verified note
    const css = read("app/globals.css");
    expect(css).toMatch(/^main \.screen-fit \{ height: calc\(100svh - 3\.25rem - 1px\); \}$/m);
    const grid = read("app/ticker-grid.tsx");
    expect(grid).toContain("fitPageSize(box.clientHeight, cols, rowH)");
    expect(grid).toContain('className="flex-1 min-h-0 overflow-hidden flex flex-col justify-center"');
  });

  it("the opening keeps its cue at the bottom of its own screen, and the header hides what scrolls under it", () => {
    const home = read("app/page.tsx");
    expect(home).toMatch(/className="open-cue absolute inset-x-0 bottom-0[^"]*"/);
    expect(read("app/layout.tsx")).toContain('<header className="border-b bg-background sticky top-0 z-40">');   // opaque, no blur
  });
});
