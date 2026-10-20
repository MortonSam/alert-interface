import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { dayMs, monthTicks, timeRows, yearTicks } from "@/lib/walkthroughAxis";

// Sam (2026-10-19, MU step 5): the P/E chart spaced points by count, so 2022 and 2023 took most of the width and 2024 to 2026 were
// squeezed at the right. On a time axis a tick's position depends only on its date.
const px = (t: number, t0: number, t1: number, width = 340) => ((t - t0) / (t1 - t0)) * width;

function series(from: string, to: string, everyDays: number): [string, number][] {
  const out: [string, number][] = [];
  for (let t = dayMs(from); t <= dayMs(to); t += everyDays * 86_400_000) out.push([new Date(t).toISOString().slice(0, 10), 10]);
  return out;
}

describe("walkthrough charts sit on a true time axis", () => {
  it("year ticks are evenly spaced, however the points are spread", () => {
    // MU-like: dense points in 2022 and 2023, sparse from 2024, and a gap
    const pts = [...series("2021-10-18", "2023-12-29", 1), ...series("2024-03-01", "2026-10-16", 30)];
    const rows = timeRows(pts.map(([d, v]) => ({ d, pe: v })), ["pe"]);
    const t0 = rows[0].t, t1 = rows[rows.length - 1].t;
    const ticks = yearTicks(t0, t1);
    expect(ticks.map((t) => new Date(t).getUTCFullYear())).toEqual([2022, 2023, 2024, 2025, 2026]);
    const gaps = ticks.slice(1).map((t, i) => px(t, t0, t1) - px(ticks[i], t0, t1));
    for (const g of gaps) expect(Math.abs(g - gaps[0]) / gaps[0]).toBeLessThan(0.005);     // 365 or 366 days apart
    // a point's position is its date's: the year from Jan 1, 2024 to Jan 1, 2025 takes as much width as 2022 did
    expect(px(dayMs("2025-01-01"), t0, t1) - px(dayMs("2024-01-01"), t0, t1)).toBeCloseTo(px(dayMs("2023-01-01"), t0, t1) - px(dayMs("2022-01-01"), t0, t1), 0);
  });

  it("a stretch with no points is a gap in the line", () => {
    const rows = timeRows([{ d: "2023-12-29", pe: 12 }, { d: "2024-03-01", pe: 14 }, { d: "2024-03-08", pe: 15 }], ["pe"]);
    expect(rows.map((r) => r.pe)).toEqual([12, null, 14, 15]);
    expect(rows[1].t).toBeGreaterThan(rows[0].t);
    expect(rows[1].t).toBeLessThan(rows[2].t);
    expect(timeRows([{ d: "2024-03-01", pe: 14 }, { d: "2024-03-11", pe: 15 }], ["pe"]).map((r) => r.pe)).toEqual([14, 15]);   // a long weekend is no gap
  });

  it("step 4's month ticks are evenly spaced too", () => {
    const t0 = dayMs("2025-10-16"), t1 = dayMs("2026-10-16");
    const ticks = monthTicks(t0, t1);
    expect(ticks.length).toBe(6);
    const gaps = ticks.slice(1).map((t, i) => (t - ticks[i]) / 86_400_000);
    for (const g of gaps) expect(g).toBeGreaterThanOrEqual(59), expect(g).toBeLessThanOrEqual(62);
  });

  it("both charts use the time axis and never draw across a gap", () => {
    const src = readFileSync(join(__dirname, "../../components/walkthrough/WalkthroughCharts.tsx"), "utf8");
    expect(src.match(/<XAxis dataKey="t" type="number" scale="time"/g)?.length).toBe(2);
    expect(src).not.toMatch(/connectNulls(?!=\{false\})/);
    expect(src).not.toMatch(/dataKey="d"/);
  });
});
