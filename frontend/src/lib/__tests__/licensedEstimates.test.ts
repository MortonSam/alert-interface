import { describe, expect, it } from "vitest";
import { estimatesShown } from "@/lib/licensedEstimates";
import { earningsMarkerLegend } from "@/lib/encodings/earningsMarkers";
import { justReportedSentence, NO_SEC_EPS_LEAD } from "@/lib/discoverSentences";
import type { JustReportedItem } from "@/lib/api";

// Nothing on the site shows an estimate, a beat, a miss, a surprise or a beat rate (Block 2, 2026-10-20), whatever a response carries.
describe("licensed estimates", () => {
  it("never shows estimates, whatever the API says", () => {
    expect(estimatesShown({ licensed_estimates: false })).toBe(false);
    expect(estimatesShown({ licensed_estimates: true })).toBe(false);
    expect(estimatesShown({})).toBe(false);
    expect(estimatesShown(null)).toBe(false);
  });

  it("the chart legend is one plain mark, and its swatch is the mark", () => {
    const legend = earningsMarkerLegend();
    expect(legend).toHaveLength(1);
    expect(legend[0].label).toBe("Earnings date");
    expect(legend.map((l) => l.label).join(" ")).not.toMatch(/beat|miss|met|no EPS data/i);
  });

  const item: JustReportedItem = { symbol: "NVDA", name: "NVIDIA", sector: null, industry: null, event_date: "2026-08-26",
    pct_change_1d: 3.1, outcome: "unknown", insight: null, vol_regime: null };

  it("Discover leads with the year-ago line, never a beat or miss, even from a response that carries an outcome", () => {
    const s = justReportedSentence({ ...item, licensed_estimates: false, eps_line: "EPS $2.46, up 127.8% from $1.08 a year ago" });
    expect(s.startsWith("EPS $2.46, up 127.8% from $1.08 a year ago")).toBe(true);
    expect(s).not.toMatch(/\b(beat|miss|estimate)/i);
    const none = justReportedSentence({ ...item, licensed_estimates: false, eps_line: null });
    expect(none.startsWith(NO_SEC_EPS_LEAD)).toBe(true);
    expect(justReportedSentence({ ...item, outcome: "beat" })).not.toMatch(/\b(beat|miss|estimate)/i);
  });
});
