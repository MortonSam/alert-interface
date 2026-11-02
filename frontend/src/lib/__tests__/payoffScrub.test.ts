import { describe, expect, it } from "vitest";
import { BS_R, type Leg, multiLegPayoffBSPS, multiLegPayoffPS } from "@/lib/black-scholes";
import { scrubValue, scrubWhen, sliderYears } from "@/lib/payoffScrub";

// BNY's $145/$155 call spread (the screenshot case, 2026-11-02): long the 145 call, short the 155
const legs: Leg[] = [
  { kind: "call", K: 145, dir: 1, mid: 5.2, sigma: 0.24 },
  { kind: "call", K: 155, dir: -1, mid: 1.6, sigma: 0.22 },
] as Leg[];
const mult = 100;
const totalDays = 18;

describe("the inspected point follows the curve for the slider's date", () => {
  it("equals the simulated curve at the inspected price on every slider date", () => {
    for (let offset = 0; offset <= totalDays; offset++) {
      const T = sliderYears(totalDays, offset);
      for (const price of [138, 145, 150, 154.06, 160]) {
        expect(scrubValue(legs, price, T, mult)).toBeCloseTo(multiLegPayoffBSPS(legs, price, T, BS_R) * mult, 10);
      }
    }
  });

  it("equals the expiration line only at expiration", () => {
    const atExpiry = (p: number) => multiLegPayoffPS(legs, p) * mult;
    expect(scrubValue(legs, 154.06, sliderYears(totalDays, totalDays), mult)).toBeCloseTo(atExpiry(154.06), 10);
    for (let offset = 0; offset < totalDays; offset++) {
      expect(Math.abs(scrubValue(legs, 150, sliderYears(totalDays, offset), mult) - atExpiry(150))).toBeGreaterThan(0.01);
    }
  });

  it("is labeled with the slider's date, and 'at expiration' only on the expiration date", () => {
    const nov10 = Date.UTC(2026, 10, 10, 17);
    expect(scrubWhen(8, nov10)).toBe("on Nov 10, 2026");
    expect(scrubWhen(0, nov10)).toBe("at expiration");
  });
});
