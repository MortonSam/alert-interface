import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { impliedBand } from "@/lib/chartAxis";

const LAST = Date.parse("2026-10-16T00:00:00Z");

describe("the implied-move band covers only the last bar to its expiration", () => {
  it("spans the last bar to the expiration, never the whole period", () => {
    expect(impliedBand(LAST, "2026-11-20", 192.96, 235.3, false)).toEqual({ x1: LAST, x2: Date.parse("2026-11-20T00:00:00Z"), y1: 192.96, y2: 235.3 });
  });
  it("is absent on the intraday periods, without a range or expiration, or with an expiration not after the last bar", () => {
    expect(impliedBand(LAST, "2026-11-20", 192.96, 235.3, true)).toBeNull();
    expect(impliedBand(LAST, null, 192.96, 235.3, false)).toBeNull();
    expect(impliedBand(LAST, "2026-11-20", null, 235.3, false)).toBeNull();
    expect(impliedBand(LAST, "2026-10-16", 192.96, 235.3, false)).toBeNull();
    expect(impliedBand(null, "2026-11-20", 192.96, 235.3, false)).toBeNull();
  });
  it("the price chart draws the band from it and reaches the expiration", () => {
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    expect(page).toMatch(/<ReferenceArea\s+x1=\{band\.x1\}\s+x2=\{band\.x2\}/);
    expect(page).toContain('domain={isIntraday ? undefined : ["dataMin", band ? band.x2 : "dataMax"]}');
    expect(page).not.toMatch(/<ReferenceArea\s+y1=\{impliedRangeLow\}/);
  });
});
