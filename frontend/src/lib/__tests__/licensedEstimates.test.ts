import { describe, expect, it } from "vitest";
import { estimatesShown } from "@/lib/licensedEstimates";
import { earningsMarkerLegend, EARNINGS_MARKER_PLAIN } from "@/lib/encodings/earningsMarkers";
import { justReportedSentence, NO_SEC_EPS_LEAD } from "@/lib/discoverSentences";
import type { JustReportedItem } from "@/lib/api";

// Backend LICENSED_ESTIMATES (services/licensed_estimates): off, every page shows the reported EPS against a year earlier.
describe("licensed estimates", () => {
  it("shows estimates unless the API says they are withheld", () => {
    expect(estimatesShown({ licensed_estimates: false })).toBe(false);
    expect(estimatesShown({ licensed_estimates: true })).toBe(true);
    expect(estimatesShown({})).toBe(true);            // a response from before the setting
    expect(estimatesShown(null)).toBe(true);
  });

  it("the chart legend has one plain mark with estimates off, and its swatch is the mark", () => {
    const off = earningsMarkerLegend(false);
    expect(off).toHaveLength(1);
    expect(off[0].label).toBe(EARNINGS_MARKER_PLAIN.label);
    expect(off[0].swatch).toEqual({ kind: "line", color: EARNINGS_MARKER_PLAIN.color, dashed: true });
    expect(earningsMarkerLegend().map((l) => l.label).join(" ")).toMatch(/beat/);
  });

  const item: JustReportedItem = { symbol: "NVDA", name: "NVIDIA", sector: null, industry: null, event_date: "2026-08-26",
    pct_change_1d: 3.1, outcome: "unknown", insight: null, vol_regime: null };

  it("Discover leads with the year-ago line, never a beat or miss", () => {
    const s = justReportedSentence({ ...item, licensed_estimates: false, eps_line: "EPS $2.46, up 127.8% from $1.08 a year ago" });
    expect(s.startsWith("EPS $2.46, up 127.8% from $1.08 a year ago")).toBe(true);
    expect(s).not.toMatch(/\b(beat|miss|estimate)/i);
    const none = justReportedSentence({ ...item, licensed_estimates: false, eps_line: null });
    expect(none.startsWith(NO_SEC_EPS_LEAD)).toBe(true);
    expect(justReportedSentence({ ...item, outcome: "beat" }).startsWith("Beat estimates")).toBe(true);    // licensed: as before
  });
});
