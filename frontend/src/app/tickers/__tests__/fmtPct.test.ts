import { describe, it, expect } from "vitest";
import { fmtPct } from "../[symbol]/fmtPct";

describe("fmtPct", () => {
  it("renders -0.04 as 0.0%", () => expect(fmtPct(-0.04)).toBe("0.0%"));
  it("renders -0.0 as 0.0%", () => expect(fmtPct(-0.0)).toBe("0.0%"));
  it("renders 0.0 as 0.0%", () => expect(fmtPct(0.0)).toBe("0.0%"));
  it("renders 0.04 as 0.0%", () => expect(fmtPct(0.04)).toBe("0.0%"));
  it("renders 1.23 as +1.2%", () => expect(fmtPct(1.23)).toBe("+1.2%"));
  it("renders -2.56 as -2.6%", () => expect(fmtPct(-2.56)).toBe("-2.6%"));
});
