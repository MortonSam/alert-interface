import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import type { ExpectedMove, OptionsRead, RealizedVol } from "@/lib/api";
import { displayedOptionFacts, priceDriftNote, priceLabel, readIsShown } from "../optionsReadFacts";

const factValues = {
  current_price: 339.07, price_as_of: "2026-09-21T17:59:00+00:00", chain_date: "2026-09-18",
  expected_move_pct: 0.0828, expected_move_dollars: 28.08, implied_range_low: 311.16, implied_range_high: 367.31,
  expiration_used: "2026-10-16", atm_strike: 340, atm_iv: 0.2463, atm_iv_as_of: "2026-09-21",
  rv_20d: 0.2145, rv_rank: 40.3, iv_rv_spread_pp: 3.2,
};
const read = {
  symbol: "AAPL", content: "…implied range is 311.16 to 367.31…", facts: {}, fact_values: factValues,
  model_used: "claude-sonnet-4-6", generated_at: "2026-09-21T18:00:00Z", cached: true, as_of: "x", available: true,
} as unknown as OptionsRead;
// The live endpoints, fetched later from a slightly different quote.
const live = { current_price: 338.75, expected_move_pct: 0.0829, expected_move_dollars: 28.08, implied_range_low: 310.91, implied_range_high: 367.06, expiration_used: "2026-10-16", atm_strike: 340 } as unknown as ExpectedMove;
const rv = { atm_iv: 0.2463, atm_iv_as_of: "2026-09-21", current_rv: 0.2145, rv_rank: 40.3, iv_rv_spread_pp: 3.2 } as unknown as RealizedVol;

describe("Ivy's Read and its rows cannot disagree", () => {
  it("while a read is shown, every row value is the read's own fact block", () => {
    const shown = displayedOptionFacts(read, live, rv);
    expect(shown.source).toBe("read");
    for (const [k, v] of Object.entries(factValues)) expect((shown as unknown as Record<string, unknown>)[k], k).toBe(v);
    expect(shown.implied_range_low).toBe(311.16);      // not the live 310.91
    expect(read.content).toContain(`${shown.implied_range_low}`);
  });

  it("without a read, rows come from the live endpoints", () => {
    const shown = displayedOptionFacts(null, live, rv);
    expect(shown.source).toBe("live");
    expect(shown.implied_range_low).toBe(310.91);
    const absent = { ...read, available: false, model_used: "none" } as OptionsRead;
    expect(readIsShown(absent)).toBe(false);
    expect(displayedOptionFacts(absent, live, rv).source).toBe("live");
  });

  it("the block is labelled with the read's price and time", () => {
    const shown = displayedOptionFacts(read, live, rv);
    expect(priceLabel(shown, () => "17:59")).toBe("priced at $339.07, last trade 17:59");
  });

  it("notes when the quote has moved more than 1% from the read's price", () => {
    const shown = displayedOptionFacts(read, live, rv);
    expect(priceDriftNote(shown, 338.75)).toBeNull();                 // 0.09% away
    const note = priceDriftNote(shown, 345.0)!;                        // 1.75% away
    expect(note).toContain("written at $339.07");
    expect(note).toContain("now $345.00");
    expect(priceDriftNote(displayedOptionFacts(null, live, rv), 345.0)).toBeNull();
  });

  it("the page renders the block and the IV/RV rows through the same function", () => {
    const src = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    expect(src.match(/displayedOptionFacts\(optionsRead, expectedMove, realizedVol\)/g)?.length).toBe(2);
    expect(src).not.toMatch(/expectedMove\.implied_range_(low|high)\b/);
    expect(src).not.toMatch(/realizedVol\?\.(atm_iv|current_rv|rv_rank|iv_rv_spread_pp)\b/);
  });
});
