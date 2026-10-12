import { describe, expect, it } from "vitest";
import { activeSection } from "@/lib/sectionSpy";

const T = (o: number, c: number, e: number, op: number, r: number) =>
  [{ id: "overview", top: o }, { id: "catalysts", top: c }, { id: "evidence", top: e }, { id: "options", top: op }, { id: "research", top: r }];

describe("section tabs", () => {
  it("lights Research on a phone when its heading is on screen under the two-row tabs (JPM, 390 x 844, Oct 11)", () => {
    // tabs end at 115px; Research's section starts at 205px (its heading at 278px); Options ended above
    expect(activeSection(T(-6000, -4000, -2500, -1400, 205), 115, 844, false)).toBe("research");
  });
  it("keeps Options while Research is still low on the screen", () => {
    expect(activeSection(T(-6000, -4000, -2500, -300, 700), 115, 844, false)).toBe("options");
  });
  it("lights the last section at the bottom of the page even when its top cannot reach the line", () => {
    expect(activeSection(T(-6000, -4000, -2500, -900, 600), 97, 1300, true)).toBe("research");
  });
  it("starts on the first section", () => {
    expect(activeSection(T(150, 1400, 2600, 3800, 5000), 97, 1300, false)).toBe("overview");
  });
});
