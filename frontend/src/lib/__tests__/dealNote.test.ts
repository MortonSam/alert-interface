import { describe, expect, it } from "vitest";
import { spreadUnavailableReason } from "@/lib/optionsReadFacts";

const NOTE = "This company has agreed to be acquired for $15.00 a share in cash, so its price now tracks the deal rather than its business. Earnings and options figures are paused.";

describe("a held ticker's IV-RV line", () => {
  it("is the deal note on its own, never inside parentheses", () => {
    const shown = { source: "live", atm_iv: null, rv_20d: 0.02, atm_iv_reason: NOTE } as never;
    const rv = { deal_note: NOTE, atm_iv: null, atm_iv_reason: NOTE, current_rv: 0.02 } as never;
    expect(spreadUnavailableReason(shown, rv, "done", false)).toBe(NOTE);
  });
});
