import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { COUNTER_LAYOUT, STAT_NUMBER_CLAMP, boxesOverlap, counterGeometry, labelWidth, numberWidth } from "@/lib/siteCounters";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");
const NUMBERS = ["117,310", "665,331", "9,903", "9,813"];           // production's counts: the longest is seven characters
const LABELS = ["option contracts captured nightly", "daily stock prices on record", "earnings reactions measured", "analyst actions measured"];

describe("the counters row never overlaps", () => {
  it.each([1024, 1280, 1440])("at %ipx the four seven-character numbers sit in four columns and no two boxes overlap", (viewport) => {
    const g = counterGeometry(viewport, NUMBERS.map(() => "1,234,567".slice(-7)));
    expect(g.columns).toBe(4);
    for (const box of g.boxes) expect(box[1] - box[0]).toBeLessThanOrEqual(g.columnWidth);      // each number fits its column
    for (let i = 0; i < g.boxes.length; i++) for (let j = i + 1; j < g.boxes.length; j++) expect(boxesOverlap(g.boxes[i], g.boxes[j]), `${i} vs ${j} at ${viewport}`).toBe(false);
    expect(g.boxes[1][0] - g.boxes[0][1]).toBeGreaterThanOrEqual(COUNTER_LAYOUT.gapX);           // a real gap, not a touch
  });

  it("the grid is 2x2 below 1024, a phone included", () => {
    expect(counterGeometry(1023, NUMBERS).columns).toBe(2);
    expect(counterGeometry(640, NUMBERS).columns).toBe(2);
    expect(counterGeometry(390, NUMBERS).columns).toBe(2);
    const phone = counterGeometry(390, NUMBERS.map(() => "1,234,567".slice(-7)));
    for (const box of phone.boxes) expect(box[1] - box[0]).toBeLessThanOrEqual(phone.columnWidth);        // seven characters fit a phone column
    expect(counterGeometry(390, NUMBERS).boxes.every(([l, r]) => l >= 0 && r <= 390 - 2 * COUNTER_LAYOUT.sidePadding.base)).toBe(true);   // a phone: the number fits the row
  });

  it("labels fit on one line from 1024 up; below it they may wrap", () => {
    for (const viewport of [1024, 1280, 1440]) {
      const g = counterGeometry(viewport, NUMBERS);
      for (const label of LABELS) expect(labelWidth(label), `${label} at ${viewport}`).toBeLessThanOrEqual(g.columnWidth);
    }
    const src = read("components/SiteCounters.tsx");
    expect(src).toContain("tracking-[.08em] text-muted-foreground mt-3 lg:whitespace-nowrap");
  });

  it("the CSS carries the model's numbers", () => {
    const src = read("components/SiteCounters.tsx");
    expect(src).toContain("grid grid-cols-2 lg:grid-cols-4 gap-x-4");
    expect(read("app/page.tsx")).toContain('"w-full max-w-5xl mx-auto px-4 sm:px-8 text-left"');
    expect(src).toContain("text-[10px] uppercase tracking-[.08em]");
    expect(COUNTER_LAYOUT.gapX).toBe(16);                                           // gap-x-4
    expect(COUNTER_LAYOUT.containerMax).toBe(1024);                                 // max-w-5xl
    const page = read("app/page.tsx");
    expect(page).toContain(`font-size: ${STAT_NUMBER_CLAMP};`);
    const section = page.match(/<section className="([^"]*)">\s*<div className=\{HOME_COL\}>\s*<p className="home-label">By the numbers<\/p>\s*<SiteCounters initial=\{initial\} \/>/)?.[1] ?? "";
    expect(section).toContain("screen-section");                                       // one screen minus the header at every width (globals.css)
    expect(section).toContain("flex items-center");                                   // the row centered vertically on that screen, on the one left edge
    expect(section).toContain("py-12");
    expect(section).not.toMatch(/100vh|min-h-/);                                      // the height comes from the one snap rule
    const layout = read("app/layout.tsx");
    expect(layout).toContain("min-h-[3.25rem]");                                      // the header height the calc subtracts
    expect(layout).toMatch(/<header className="[^"]*border-b[^"]*sticky top-0/);      // and its one-pixel border
    const challenge = page.slice(page.indexOf("4. The Challenge"), page.indexOf("The challenge"));
    expect(challenge).not.toContain("min-h-[100svh]");                              // normal section spacing after the counters
    expect(challenge).toContain("py-12 sm:py-0");                                    // phone spacing (gaps near 96px), a full screen from 640px up
    expect(numberWidth("117,310", 60)).toBeCloseTo((6 * 0.631 + 0.241) * 60, 5);
  });
});
