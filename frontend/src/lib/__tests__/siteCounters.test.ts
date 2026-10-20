import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { COUNTER_CSS, COUNTER_LAYOUT, boxesOverlap, counterGeometry, numEm, rowWidth } from "@/lib/siteCounters";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");
const LIVE = ["154,237", "671,734", "9,932", "9,840"];               // production's counts on 2026-10-19, when they ran together at 1440
const LONG = ["1,234,567", "12,345,678", "99,999", "9"];             // longer figures than today's

/** The gaps between neighbouring boxes on each grid row. */
function gaps(viewport: number, numbers: string[]): number[] {
  const g = counterGeometry(viewport, numbers);
  const out: number[] = [];
  for (let i = 0; i + 1 < g.boxes.length; i++) if (Math.floor(i / g.columns) === Math.floor((i + 1) / g.columns)) out.push(g.boxes[i + 1][0] - g.boxes[i][1]);
  return out;
}

describe("the counters never touch", () => {
  it.each([1024, 1280, 1440, 1920])("at %ipx no two boxes overlap and each gap is at least 24px", (viewport) => {
    for (const numbers of [LIVE, LONG]) {
      const g = counterGeometry(viewport, numbers);
      for (const box of g.boxes) expect(box[1] - box[0]).toBeLessThanOrEqual(g.columnWidth);
      for (let i = 0; i < g.boxes.length; i++) for (let j = i + 1; j < g.boxes.length; j++)
        if (Math.floor(i / g.columns) === Math.floor(j / g.columns)) expect(boxesOverlap(g.boxes[i], g.boxes[j]), `${i} vs ${j} at ${viewport}`).toBe(false);
      for (const gap of gaps(viewport, numbers)) expect(gap).toBeGreaterThanOrEqual(24);
    }
  });

  it("four across only where four fit; otherwise two by two, from 360 to 1920", () => {
    for (let v = 360; v <= 1920; v += 8) {
      const g = counterGeometry(v, LIVE);
      expect(g.columns).toBe(rowWidth(v) >= COUNTER_LAYOUT.fourAcrossMinPx ? 4 : 2);
      for (const gap of gaps(v, LIVE)) expect(gap, `at ${v}`).toBeGreaterThanOrEqual(24);
      for (const box of g.boxes) expect(box[1], `at ${v}`).toBeLessThanOrEqual(rowWidth(v) + 0.01);
    }
    expect(counterGeometry(1440, LIVE).columns).toBe(4);
    expect(counterGeometry(390, LIVE).columns).toBe(2);
  });

  it("the figures shrink to fit rather than overflow: 1440's row is 960px, not 1024", () => {
    expect(rowWidth(1440)).toBe(960);
    const g = counterGeometry(1440, LIVE);
    expect(g.fontSize).toBeLessThan(COUNTER_LAYOUT.fontMaxPx);
    expect(numEm(["154,237"])).toBeCloseTo((6 * 0.631 + 0.241) * 1.06, 3);
  });

  it("the CSS and the component carry the model", () => {
    const page = read("app/page.tsx");
    expect(page).toContain("${COUNTER_CSS}");
    expect(COUNTER_CSS).toContain(`column-gap: ${COUNTER_LAYOUT.gapPx}px`);
    expect(COUNTER_CSS).toContain(`@container (min-width: ${COUNTER_LAYOUT.fourAcrossMinPx}px)`);
    expect(COUNTER_CSS).toContain("container-type: inline-size");
    expect(COUNTER_CSS).toContain("font-variant-numeric: tabular-nums");
    expect(page).toContain('"w-full max-w-5xl mx-auto px-4 sm:px-8 text-left"');
    const src = read("components/SiteCounters.tsx");
    expect(src).toContain('className="counters w-full"');
    expect(src).toContain('className="counters-grid w-full text-left"');
    expect(src).toContain('"--num-em": numEm(');
    expect(src).not.toContain("whitespace-nowrap`");                       // labels wrap inside their column, never into the next
    const section = page.match(/<section className="([^"]*)">\s*<div className=\{HOME_COL\}>\s*<p className="home-label">By the numbers<\/p>\s*<SiteCounters initial=\{initial\} \/>/)?.[1] ?? "";
    expect(section).toContain("screen-section");
    expect(section).toContain("flex items-center");
  });
});
