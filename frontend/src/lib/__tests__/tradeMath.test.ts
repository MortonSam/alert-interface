import { describe, expect, it } from "vitest";
import {
  BREAKEVEN_STRETCH_FLAG, ESTIMATE_NOTE, breakevenPrice, breakevenStretch, chancePastBreakeven, estimateReceipt, expiryPnl,
  gainAtImpliedMove, impliedMovePrice, stretchLine, type DebitTrade,
} from "@/lib/tradeMath";

// Worked examples, each checked by hand and against Python's math.erf (the chances below to four places).
const CALL: DebitTrade = { direction: "bullish", strike: 105, spreadStrike: null, costPerShare: 2 };     // spot 100
const PUT: DebitTrade = { direction: "bearish", strike: 95, spreadStrike: null, costPerShare: 1.5 };
const SPREAD: DebitTrade = { direction: "bullish", strike: 100, spreadStrike: 110, costPerShare: 4 };

describe("expiry profit and loss, per contract", () => {
  it("a long call: intrinsic less the premium, times 100", () => {
    expect(expiryPnl(CALL, 100)).toBe(-200);           // expires worthless: the $2 premium, $200
    expect(expiryPnl(CALL, 107)).toBe(0);              // breakeven
    expect(expiryPnl(CALL, 112)).toBe(500);            // (112 - 105 - 2) x 100
  });
  it("a long put mirrors it", () => {
    expect(expiryPnl(PUT, 90)).toBe(350);              // (95 - 90 - 1.5) x 100
    expect(expiryPnl(PUT, 100)).toBe(-150);
  });
  it("a spread's value is capped at its width", () => {
    expect(expiryPnl(SPREAD, 125)).toBe(600);          // (10 - 4) x 100, however far it runs
    expect(expiryPnl(SPREAD, 104)).toBe(0);
    expect(expiryPnl(SPREAD, 95)).toBe(-400);
  });
  it("breakeven is the long strike plus or less the cost", () => {
    expect(breakevenPrice(CALL)).toBe(107);
    expect(breakevenPrice(PUT)).toBe(93.5);
    expect(breakevenPrice(SPREAD)).toBe(104);
  });
});

describe("the two figures that replace Unlimited", () => {
  it("the gain if the stock moves by the implied move", () => {
    expect(impliedMovePrice(100, 8, "bullish")).toBeCloseTo(108, 10);
    expect(gainAtImpliedMove(CALL, 100, 8)).toBeCloseTo(100, 6);        // stock at $108: (108 - 105 - 2) x 100
    expect(gainAtImpliedMove(CALL, 100, 5)).toBeCloseTo(-200, 6);       // stock at $105: the call is worth nothing
    expect(gainAtImpliedMove(PUT, 100, 8)).toBeCloseTo(150, 6);         // stock at $92: (95 - 92 - 1.5) x 100
  });
  it("the chance of finishing past breakeven, lognormal at the at-the-money implied volatility", () => {
    expect(chancePastBreakeven(100, 107, 40, 30, "bullish")!).toBeCloseTo(0.2587, 4);
    expect(chancePastBreakeven(100, 93.5, 40, 30, "bearish")!).toBeCloseTo(0.2985, 4);
    expect(chancePastBreakeven(100, 104, 35, 21, "bullish")!).toBeCloseTo(0.3053, 4);
    expect(chancePastBreakeven(100, 100, 40, 30, "bullish")!).toBeCloseTo(0.4771, 4);    // under half: the median finish is today's price
    expect(chancePastBreakeven(100, 107, 0, 30, "bullish")).toBeNull();
    expect(chancePastBreakeven(100, 107, 40, 0, "bullish")).toBeNull();
  });
  it("the receipt and the note say what the estimate is", () => {
    expect(estimateReceipt(40, 30, 100, "2026-10-14")).toBe("At-the-money implied volatility 40.0%, 30 days to expiration, stock at $100.00 in the Oct 14, 2026 options data.");
    expect(ESTIMATE_NOTE).toBe("An estimate from option prices, not a forecast.");
  });
});

describe("a breakeven past 1.5 times the implied move is flagged", () => {
  it("measures the move breakeven needs against the implied move", () => {
    expect(breakevenStretch(100, 107, 4)!.ratio).toBeCloseTo(1.75, 10);
    expect(stretchLine(100, 107, 4)).toBe("Breakeven needs a 7.0% move, 1.8 times the 4.0% the options imply.");
    expect(stretchLine(100, 107, 5)).toBeNull();                          // 7% is 1.4 times 5%
    expect(stretchLine(100, 107.5, 5)).toBeNull();                        // exactly 1.5 times: not past it
    expect(BREAKEVEN_STRETCH_FLAG).toBe(1.5);
  });
});

describe("the payoff chart's scrub", () => {
  it("maps a finger's x to a stock price across the plot, clamped at its ends", async () => {
    const { priceAtX } = await import("@/lib/tradeMath");
    // a 390-wide chart, plot from 68 to 382, prices $90 to $120
    expect(priceAtX(68, 390, 68, 8, 90, 120)).toBe(90);
    expect(priceAtX(382, 390, 68, 8, 90, 120)).toBe(120);
    expect(priceAtX(225, 390, 68, 8, 90, 120)).toBeCloseTo(105, 10);      // the middle of the plot
    expect(priceAtX(10, 390, 68, 8, 90, 120)).toBe(90);                   // on the y-axis: the lowest price
    expect(priceAtX(500, 390, 68, 8, 90, 120)).toBe(120);
  });
});

describe("the payoff chart's range takes in the strikes and breakeven", () => {
  it("widens the implied range to the far strike and breakeven, 3% past them", async () => {
    const { payoffRange } = await import("@/lib/tradeMath");
    const [lo, hi] = payoffRange(335.37, 389.51, 362.44, [400, 403.55]);
    expect(lo).toBe(335.37);
    expect(hi).toBeCloseTo(403.55 * 1.03, 6);
    expect(payoffRange(null, null, 100, [])).toEqual([80, 120]);
  });
  it("never says 1.5 times for a ratio past the 1.5 flag", async () => {
    const { stretchLine } = await import("@/lib/tradeMath");
    expect(stretchLine(362.44, 403.55, 7.47)).toBe("Breakeven needs an 11.3% move, 1.52 times the 7.5% the options imply.");
  });
});

describe("Build a Trade wording (Sam, 2026-10-19)", () => {
  it("chooses a or an by how the number is read", async () => {
    const { articleFor } = await import("@/lib/tradeMath");
    for (const n of ["8", "8.0", "11.3", "11", "18", "18.4", "80", "80.0", "85.5", "89.9", "800", "8,000", "11,300", "18,000"]) expect([n, articleFor(n)]).toEqual([n, "an"]);
    for (const n of ["7.5", "1.5", "0.8", "1", "10", "12.0", "19", "90", "100", "110", "118", "180", "1,800", "111"]) expect([n, articleFor(n)]).toEqual([n, "a"]);
  });
  it("flags with an article that fits the number", async () => {
    const { stretchLine } = await import("@/lib/tradeMath");
    expect(stretchLine(100, 118, 10)).toBe("Breakeven needs an 18.0% move, 1.8 times the 10.0% the options imply.");
    expect(stretchLine(100, 185, 50)).toBe("Breakeven needs an 85.0% move, 1.7 times the 50.0% the options imply.");
    expect(stretchLine(100, 92.5, 4)).toBe("Breakeven needs a 7.5% move, 1.9 times the 4.0% the options imply.");
  });
  it("labels the implied move by direction and states absences in full sentences", async () => {
    const { impliedMoveLabel, NO_IMPLIED_MOVE, NO_IMPLIED_VOL } = await import("@/lib/tradeMath");
    expect(impliedMoveLabel("TSLA", "bullish", 7.47)).toBe("If TSLA rises the 7.5% the options imply by expiration");
    expect(impliedMoveLabel("TSLA", "bearish", 7.47)).toBe("If TSLA falls the 7.5% the options imply by expiration");
    expect(NO_IMPLIED_MOVE).toBe("Not shown because the options data has no implied move.");
    expect(NO_IMPLIED_VOL).toBe("Not shown because the options data has no implied volatility.");
  });
  it("dates the receipt in the site format", async () => {
    const { estimateReceipt, ESTIMATE_NOTE } = await import("@/lib/tradeMath");
    expect(`${estimateReceipt(59.1, 9, 362.44, "2026-10-14")} ${ESTIMATE_NOTE}`).toBe(
      "At-the-money implied volatility 59.1%, 9 days to expiration, stock at $362.44 in the Oct 14, 2026 options data. An estimate from option prices, not a forecast.");
  });
});
