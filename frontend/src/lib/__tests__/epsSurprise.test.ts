import { describe, it, expect } from "vitest";
import { fmtEpsSurprise } from "../epsSurprise";
import { EPS_SURPRISE_PCT_CAP } from "../thresholds";

describe("EPS surprise display", () => {
  it("TTWO May 2025: near-zero estimate shows dollars, never -42060%", () => {
    const out = fmtEpsSurprise({ eps_surprise_pct: null, eps_surprise_dollars: -21.03, eps_estimate: "0.0500", eps_actual: "-20.9800" })!;
    expect(out.text).toBe("-$21.03 vs est.");
    expect(out.text).not.toContain("%");
    expect(out.title).toContain("near zero");
  });

  it("TTWO May 2024: -1636.7% is capped, with the exact dollars in the tooltip", () => {
    const out = fmtEpsSurprise({ eps_surprise_pct: -1636.7, eps_surprise_dollars: -16.04, eps_surprise_display_pct: -999, eps_surprise_capped: true, eps_estimate: "-0.98", eps_actual: "-17.02" })!;
    expect(out.text).toBe(`<-${EPS_SURPRISE_PCT_CAP}%`);
    expect(out.title).toContain("-$16.04");
    expect(out.title).toContain("-1637%");
  });

  it("an ordinary surprise prints as before", () => {
    expect(fmtEpsSurprise({ eps_surprise_pct: 19.3, eps_surprise_display_pct: 19.3, eps_surprise_capped: false })!.text).toBe("+19.3%");
    expect(fmtEpsSurprise({ eps_surprise_pct: null })).toBeNull();
  });
});
