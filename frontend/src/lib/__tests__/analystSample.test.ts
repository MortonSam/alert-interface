import { describe, it, expect } from "vitest";
import { analystSampleLabel, analystSampleFooter } from "@/lib/analystSample";

describe("analyst sample wording", () => {
  it("names both counts when actions and sessions differ", () => {
    expect(analystSampleLabel(6, 4, "in 5 yr")).toBe("n = 6 actions across 4 sessions in 5 yr");
    expect(analystSampleFooter(13, 11)).toBe("Based on n = 13 actions across 11 sessions");
  });
  it("shows the plain count when every action was its own session", () => {
    expect(analystSampleLabel(4, 4, "in 5 yr")).toBe("4 in 5 yr");
    expect(analystSampleFooter(4, 4)).toBe("Based on 4 actions");
  });
});
