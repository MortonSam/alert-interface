import { describe, it, expect } from "vitest";
import { analystSampleLabel, analystSampleFooter, hasAnalystSignal, streetPulseLine } from "@/lib/analystSample";

describe("analyst sample wording", () => {
  it("names both counts when actions and sessions differ", () => {
    expect(analystSampleLabel(6, 4, "in 5 yr")).toBe("n = 6 actions across 4 sessions in 5 yr");
    expect(analystSampleFooter(13, 11)).toBe("Based on n = 13 actions across 11 sessions");
  });
  it("shows the plain count when every action was its own session", () => {
    expect(analystSampleLabel(4, 4, "in 5 yr")).toBe("4 in 5 yr");
    expect(analystSampleFooter(4, 4)).toBe("Based on 4 actions");
  });
  it("never says 'across 0 sessions' for a row not yet recomputed", () => {
    expect(analystSampleLabel(6, 0, "in 5 yr")).toBe("6 in 5 yr");
    expect(analystSampleFooter(13, 0)).toBe("Based on 13 actions");
  });
  it("insight gate treats a stored median with 0 sessions as no data", () => {
    expect(hasAnalystSignal(-4.05, 0)).toBe(false);
    expect(hasAnalystSignal(-4.05, 3)).toBe(true);
    expect(hasAnalystSignal(null, 3)).toBe(false);
  });
});

describe("Street Pulse calls a move a reaction only past the stock's usual daily move", () => {
  const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
  const base = { median_1d_upgrade: 0.4, median_1d_downgrade: -2.6, upgrade_sessions: 9, downgrade_sessions: 12,
    upgrade_5d_continuation_pct: 55, downgrade_5d_continuation_pct: 64, median_abs_daily_move_pct: 1.1 };
  it("a median past the usual move is a reaction", () => {
    expect(streetPulseLine(base, pct, "five sessions later")).toBe("Downgrades tend to hit, median -2.6% on the day, still lower five sessions later 64% of the time.");
  });
  it("a median inside the usual move is no clear reaction", () => {
    expect(streetPulseLine({ ...base, median_1d_downgrade: -0.6 }, pct, "five sessions later"))
      .toBe("Downgrades have brought no clear reaction, a median -0.6% on the day against a usual daily move of ±1.1%.");
  });
  it("without the usual move there is no claim either way", () => {
    expect(streetPulseLine({ ...base, median_abs_daily_move_pct: null }, pct, "x")).toBeNull();
  });
});
