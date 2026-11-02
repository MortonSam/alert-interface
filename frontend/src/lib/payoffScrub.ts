// Build a Trade's inspected point (Sam, 2026-11-02): the dot, the headline figure and its label read the curve for the date the
// slider is on, so "BNY at $154.06 on Nov 10, 2026" is the simulated value on Nov 10; only at expiration is it the expiration line.

import { BS_R, type Leg, multiLegPayoffBSPS } from "@/lib/black-scholes";
import { fmtDate } from "@/lib/dates";

/** The slider's time left to expiration in years: the same figure the drawn curve uses. */
export function sliderYears(totalDays: number, dateOffset: number): number {
  return Math.max(0, (totalDays - dateOffset) / 365.25);
}

/** The profit or loss at `price` on the slider's date, from the same model as the drawn curve (at expiration, intrinsic value). */
export function scrubValue(legs: Leg[], price: number, years: number, mult: number): number {
  return multiLegPayoffBSPS(legs, price, years, BS_R) * mult;
}

/** "at expiration" on the expiration date, else "on Nov 10, 2026": what the headline's figure is the value at. */
export function scrubWhen(daysLeft: number, dateMs: number): string {
  return daysLeft <= 0 ? "at expiration" : `on ${fmtDate(dateMs) ?? ""}`;
}
