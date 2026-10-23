// The Options Details rows in plain words (Sam, 2026-10-22, verbatim). Every figure comes from the row's own fact; the daily
// figure is computed here only, and the spread's words follow the thresholds in lib/thresholds (mirrored from the backend by test).
import { SPREAD_CHEAP_PP, SPREAD_RICH_PP } from "@/lib/thresholds";

export const TRADING_DAYS_PER_YEAR = 252;

export const ROW_LABELS = {
  iv: "How much options expect it to swing",
  rv: "How much it has actually swung",
  spread: "Options against its recent swings",
} as const;

const one = (x: number) => x.toFixed(1);

/** The typical day's figure from an annual one (0-1 decimal in, percent string out): annual / sqrt(252), one decimal. */
export function dailyPct(annual: number): string {
  return one((annual * 100) / Math.sqrt(TRADING_DAYS_PER_YEAR));
}

/** "41.2% a year, about 2.6% on a typical day, from the options nearest today's price that end at least 7 days out (as of Oct 19, 2026)" */
export function ivRowValue(iv: number, asOf: string | null): string {
  const tail = asOf ? ` (as of ${asOf})` : "";
  return `${one(iv * 100)}% a year, about ${dailyPct(iv)}% on a typical day, from the options nearest today's price that end at least 7 days out${tail}`;
}

/** "38.0% a year, about 2.4% on a typical day, from its daily moves over the last 20 trading days (as of Oct 19, 2026)" */
export function rvRowValue(rv: number, windowDays: number, asOf: string | null): string {
  const tail = asOf ? ` (as of ${asOf})` : "";
  return `${one(rv * 100)}% a year, about ${dailyPct(rv)}% on a typical day, from its daily moves over the last ${windowDays} trading days${tail}`;
}

/** The spread in points (implied minus realized, annual), worded by the same thresholds as the backend's spread_label. */
export function spreadRowValue(spreadPts: number): string {
  if (spreadPts > SPREAD_RICH_PP) return `Options expect ${one(spreadPts)} points more swing than the stock has shown lately, so they look pricey`;
  if (spreadPts < SPREAD_CHEAP_PP) return `Options expect ${one(-spreadPts)} points less swing than the stock has shown lately, so they look cheap`;
  return "Options expect about the same swing the stock has shown lately";
}
