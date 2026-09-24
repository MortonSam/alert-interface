import { describe, it, expect } from "vitest";
import { rowStrings, fmtDollars, fmtMovePct } from "@/lib/optionFactFormat";

// The same fact block the backend test (test_options_read_facts.py) feeds format_facts.
// The strings below are what format_facts produced for it; the rows must print the same.
const BLOCK = {
  atm_strike: 412.5, expected_move_pct: 0.0828, expected_move_dollars: 28.08,
  implied_range_low: 384.42, implied_range_high: 440.58,
};
const PROSE = {
  atm_strike: "$412.50",
  expected_move_pct: "\u00B18.3%",
  expected_move_dollars: "\u00B1$28.08",
  implied_range: "$384.42 - $440.58",
};

describe("rows and Ivy's Read print the same numbers", () => {
  it("every row string equals the prose string from one fact block", () => {
    expect(rowStrings(BLOCK)).toEqual(PROSE);
  });
  it("a strike is never rounded to the whole dollar", () => {
    expect(fmtDollars(412.5)).toBe("$412.50");      // was "$413" in the ATM row
    expect(fmtDollars(340)).toBe("$340.00");
  });
  it("absent values stay absent, never a placeholder", () => {
    expect(rowStrings({ atm_strike: null, expected_move_pct: null, expected_move_dollars: null, implied_range_low: null, implied_range_high: 440.58 }))
      .toEqual({ atm_strike: null, expected_move_pct: null, expected_move_dollars: null, implied_range: null });
    expect(fmtMovePct(null)).toBeNull();
  });
});
