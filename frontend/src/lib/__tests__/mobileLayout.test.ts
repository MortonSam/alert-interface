import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("390px layout (audit item 24)", () => {
  it("every page keeps a 16px gutter on a phone and 32px from sm up", () => {
    for (const page of ["app/tickers/[symbol]/page.tsx", "app/build/page.tsx", "app/discover/page.tsx", "app/watchlist/page.tsx", "app/theses/page.tsx"]) {
      const src = read(page);
      expect(src, page).not.toMatch(/<main className="min-h-screen p-8">/);
      expect(src, page).toContain('<main className="min-h-screen p-4 sm:p-8">');
    }
    expect(read("app/page.tsx")).not.toMatch(/className="[^"]*(?<!sm:)\bpx-8\b/);
    expect(read("app/layout.tsx")).toContain("px-4 sm:px-8");
    expect(read("app/disclosures/page.tsx")).toContain("px-4 sm:px-6");
  });

  it("the header nav wraps instead of scrolling sideways, and the Ivy CTA row and tabs wrap", () => {
    expect(read("app/layout.tsx")).toMatch(/min-h-\[3\.25rem\][^"]*flex flex-wrap items-center gap-x-4 gap-y-1 sm:gap-6/);
    expect(read("app/layout.tsx")).not.toMatch(/h-\[3\.25rem\] flex items-center gap-6/);
    const ivy = read("app/ivy/page.tsx");
    expect(ivy).toContain("flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 sm:gap-6");
    expect(ivy).not.toMatch(/font-display text-xl font-bold text-foreground whitespace-nowrap/);
    expect(ivy).toContain('<div className="flex flex-wrap gap-3">');
    expect(read("app/ivy/layout.tsx")).toContain('className="flex flex-wrap gap-1 border-b mb-6"');
    const ticker = read("app/tickers/[symbol]/page.tsx");
    expect(ticker).toContain("-mx-4 px-4 sm:-mx-8 sm:px-8");
    expect(ticker).toContain("flex flex-wrap gap-x-4 gap-y-1.5 sm:gap-6 py-3");
  });

  it("the distribution table fits with its N column, at one type size, right-aligned values intact", () => {
    const ticker = read("app/tickers/[symbol]/page.tsx");
    const panel = ticker.slice(ticker.indexOf("function DistributionPanel"), ticker.indexOf("function ReactionsTable"));
    expect(panel.match(/pr-2 sm:pr-4/g)?.length).toBe(10);       // 5 headers, 5 cells
    expect(panel).not.toMatch(/(?<!sm:)pr-4\b/);
    expect(panel).toMatch(/text-right[^>]*w-8">N<\/th>/);
    expect(panel).toContain('<table className="w-full table-fixed text-xs">');   // fixed columns: N never scrolls out of view
    expect(ticker).toContain('className="tabular-nums font-medium text-xs sm:text-sm text-foreground"');
    expect(panel.match(/text-right/g)?.length).toBeGreaterThanOrEqual(10);
  });

  it("Build stacks its tiles and grids on a phone and wraps its button rows", () => {
    const build = read("app/build/page.tsx");
    expect(build).toContain('cn("grid gap-4 grid-cols-1", ivyDecided ? "sm:grid-cols-2" : "sm:grid-cols-3")');
    expect(build.match(/grid grid-cols-1 sm:grid-cols-3 gap-4/g)?.length).toBe(2);   // cost/risk and the alternative
    expect(build).toContain('<div className="grid grid-cols-1 sm:grid-cols-2 gap-5">');   // the confirm grid
    expect(build).not.toMatch(/"grid grid-cols-[23] gap-[45]/);
    expect(build.match(/flex flex-wrap gap-3 pt-1/g)?.length).toBe(2);
    expect(build).not.toMatch(/<div className="flex gap-3 pt-1">/);
    expect(build.match(/bg-transparent px-4 sm:px-6 py-6/g)?.length).toBe(2);
  });

  it("the Put/Call row keeps its label on one line and stacks the value block beneath it on a phone", () => {
    const ticker = read("app/tickers/[symbol]/page.tsx");
    expect(ticker).toContain('className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-y-0.5 py-1.5 border-b border-border/40" data-testid="put-call-row"');
    const row = ticker.slice(ticker.indexOf('data-testid="put-call-row"'), ticker.indexOf("{dataError &&"));
    expect(row).toContain('text-sm text-muted-foreground whitespace-nowrap');
    expect(row).toContain('font-mono text-sm font-medium tabular-nums sm:text-right');
  });
});
