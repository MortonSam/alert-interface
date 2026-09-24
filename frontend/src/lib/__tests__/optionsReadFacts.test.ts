import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import type { ExpectedMove, OptionsRead, RealizedVol } from "@/lib/api";
import { displayedOptionFacts, priceDriftNote, priceLabel, readIsShown, rvUnavailableReason, RV_NO_REASON_RECORDED, ivUnavailableReason, spreadUnavailableReason } from "../optionsReadFacts";

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
    // computed once (useMemo) and read by the chart band, the expected-move block and the IV/RV rows
    expect(src.match(/displayedOptionFacts\(optionsRead, expectedMove, realizedVol\)/g)?.length).toBe(1);
    expect(src.match(/shownOptionFacts/g)!.length).toBeGreaterThanOrEqual(5);
    expect(src).not.toMatch(/expectedMove\.implied_range_(low|high)\b/);
    expect(src).not.toMatch(/realizedVol\?\.(atm_iv|current_rv|rv_rank|iv_rv_spread_pp)\b/);
  });
});

describe("RV unavailable always carries its reason", () => {
  const rvReason = "Realized volatility could not be computed reliably for this ticker";
  const liveRv = { current_rv: 0.65, rv_rank: 27.8, as_of: "2026-09-22", reason: null } as unknown as Parameters<typeof rvUnavailableReason>[1];
  it("read mode: the read's stored rv_reason, even when the live endpoint now serves RV", () => {
    const shown = { source: "read", rv_20d: null, rv_reason: rvReason } as unknown as Parameters<typeof rvUnavailableReason>[0];
    expect(rvUnavailableReason(shown, liveRv, "done")).toBe(`${rvReason} (when Ivy's Read was written)`);
    const noReason = { source: "read", rv_20d: null } as unknown as Parameters<typeof rvUnavailableReason>[0];
    expect(rvUnavailableReason(noReason, liveRv, "done")).toBe("Realized volatility was unavailable when Ivy's Read was written");
  });
  it("live mode: the endpoint's reason, then the load state, never an empty string", () => {
    const shown = { source: "live", rv_20d: null } as unknown as Parameters<typeof rvUnavailableReason>[0];
    const absent = { current_rv: null, reason: rvReason } as unknown as Parameters<typeof rvUnavailableReason>[1];
    expect(rvUnavailableReason(shown, absent, "empty")).toBe(rvReason);
    expect(rvUnavailableReason(shown, null, "loading")).toBe("Realized volatility is still loading");
    expect(rvUnavailableReason(shown, null, "error")).toBe("Realized volatility could not be loaded");
    expect(rvUnavailableReason(shown, { current_rv: null, reason: null } as unknown as Parameters<typeof rvUnavailableReason>[1], "empty")).toBe(RV_NO_REASON_RECORDED);
  });
  it("live mode carries the endpoint's reason and date into the displayed facts", () => {
    const rv = { current_rv: null, rv_rank: null, as_of: "2026-09-21", reason: rvReason } as unknown as Parameters<typeof displayedOptionFacts>[2];
    const f = displayedOptionFacts(null, null, rv);
    expect(f.source).toBe("live");
    expect(f.rv_reason).toBe(rvReason);
    expect(f.rv_as_of).toBe("2026-09-21");
  });
});

describe("IV unavailable and the spread row always carry their reason", () => {
  type Shown = Parameters<typeof ivUnavailableReason>[0];
  type Rv = Parameters<typeof ivUnavailableReason>[1];
  const ivReason = "No ATM implied volatility in the last 3 days (the 2026-09-23 snapshot recorded none: no implied volatility on the ATM strike for expiration 2026-10-16); last: 46.9% on 2026-09-21";
  it("read mode: the read's stored atm_iv_reason, dated to the read", () => {
    const shown = { source: "read", atm_iv: null, atm_iv_reason: ivReason, rv_20d: 0.65 } as unknown as Shown;
    expect(ivUnavailableReason(shown, null, "done")).toBe(`${ivReason} (when Ivy's Read was written)`);
    const noReason = { source: "read", atm_iv: null, rv_20d: 0.65 } as unknown as Shown;
    expect(ivUnavailableReason(noReason, null, "done")).toBe("Implied volatility was unavailable when Ivy's Read was written");
  });
  it("live mode: the endpoint's reason, then the load state, never empty", () => {
    const shown = { source: "live", atm_iv: null, rv_20d: 0.65 } as unknown as Shown;
    expect(ivUnavailableReason(shown, { atm_iv: null, atm_iv_reason: ivReason } as unknown as Rv, "done")).toBe(ivReason);
    expect(ivUnavailableReason(shown, null, "loading")).toBe("Implied volatility is still loading");
    expect(ivUnavailableReason(shown, null, "error")).toBe("Implied volatility could not be loaded");
    expect(ivUnavailableReason(shown, { atm_iv: null } as unknown as Rv, "empty")).toBe("Implied volatility is unavailable and no reason was recorded");
  });
  it("live mode carries atm_iv_reason into the displayed facts", () => {
    const f = displayedOptionFacts(null, null, { current_rv: 0.65, atm_iv: null, atm_iv_reason: ivReason, reason: null } as unknown as Parameters<typeof displayedOptionFacts>[2]);
    expect(f.atm_iv_reason).toBe(ivReason);
  });
  it("spread row names the missing side with its reason, or the consistency check, or nothing when shown", () => {
    const ivMissing = { source: "read", atm_iv: null, atm_iv_reason: ivReason, rv_20d: 0.65 } as unknown as Shown;
    expect(spreadUnavailableReason(ivMissing, null, "done", false)).toBe(`IV-RV spread unavailable: implied volatility is missing (${ivReason} (when Ivy's Read was written))`);
    const rvMissing = { source: "read", atm_iv: 0.47, rv_20d: null, rv_reason: "Realized volatility could not be computed reliably for this ticker" } as unknown as Shown;
    expect(spreadUnavailableReason(rvMissing, null, "done", false)).toContain("realized volatility is missing (Realized volatility could not be computed reliably");
    const both = { source: "live", atm_iv: null, rv_20d: null } as unknown as Shown;
    expect(spreadUnavailableReason(both, null, "error", false)).toContain("both missing");
    const present = { source: "read", atm_iv: 0.47, rv_20d: 0.65 } as unknown as Shown;
    expect(spreadUnavailableReason(present, null, "done", false)).toBe("IV-RV spread unavailable: the stored spread does not match the IV and RV shown");
    expect(spreadUnavailableReason(present, null, "done", true)).toBeNull();
  });
});
