import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { datasetAgeLine, datasetsStale, fmtIsoDateTime, fmtQuoteDateTime, freshnessLine, nightlyWord, optionsCadencePhrase, optionsDataPhrase, premiumSourcePhrase, priceSourceLine, priceStateLine, priceAsOfPhrase } from "../freshness";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return name === "__tests__" ? [] : sourceFiles(full);
    return /\.tsx?$/.test(name) ? [full] : [];
  });
}

describe("freshness wording", () => {
  it("the price source, the cadence words and every quote's date come from the record and the data, never from copy", () => {
    const cadence = { nightly: { per_day: 1, utc_hour: 6, local_time: "02:00", clock: "America/New_York" },
                      options: { per_day: 1, captured_local: "16:05", clock: "America/New_York", fresh_sessions: 2 },
                      quotes: { source: "Finnhub", delay_statement: null, delay_checked: "2026-10-05", dated_by: "each quote's own last-trade time" } };
    expect(priceSourceLine(cadence)).toBe("Prices from Finnhub, each dated by its last trade");
    expect(priceSourceLine({ ...cadence, quotes: { ...cadence.quotes, delay_statement: "delayed 15 minutes" } })).toBe("Prices from Finnhub, delayed 15 minutes");
    expect(priceSourceLine(null)).toBe("Prices from the quote source, each dated by its last trade");
    expect(nightlyWord(cadence)).toBe("nightly");
    expect(nightlyWord({ ...cadence, nightly: { ...cadence.nightly, per_day: 2 } })).toBe("2 times a day");
    expect(nightlyWord(null)).toBeNull();
    expect(optionsCadencePhrase(cadence)).toBe("updated once a day");
    expect(optionsDataPhrase("2026-10-01", cadence)).toBe("options data as of 2026-10-01, updated once a day");
    expect(optionsDataPhrase("2026-10-01")).toBe("options data as of 2026-10-01");           // no record: no cadence claim
    expect(freshnessLine("Earnings history as of 5h ago", cadence)).toBe("Prices from Finnhub, each dated by its last trade · Earnings history as of 5h ago");
    expect(freshnessLine(null, cadence)).toBe("Prices from Finnhub, each dated by its last trade · Research data refreshed nightly");
    expect(freshnessLine(null)).toBe("Prices from the quote source, each dated by its last trade · Research data from the stored refresh steps");
    expect(fmtQuoteDateTime(1759694400)).toBe("Oct 5, 4:00 PM ET");                            // 2026-10-05 20:00Z
    expect(fmtIsoDateTime("2026-10-05T20:00:00+00:00")).toBe("Oct 5, 4:00 PM ET");
    expect(fmtQuoteDateTime(null)).toBeNull();
    // each page dates its line by the oldest dataset it shows, never by the global stamp
    const ago = (iso: string) => (iso.startsWith("2026-10-05") ? "2h ago" : "30h ago");
    const datasets = {
      reactions: { at: "2026-10-05T06:30:00+00:00", ok: true, failed: [] },
      analyst: { at: "2026-10-04T06:30:00+00:00", ok: true, failed: [] },
      iv: { at: "2026-10-05T07:00:00+00:00", ok: false, failed: ["IV + RV snapshot (snapshot_iv)"] },
      chains: { at: null, ok: false, failed: ["Courier ingest"] },
    };
    expect(datasetAgeLine(datasets, ["reactions"], ago)).toBe("Earnings history as of 2h ago");
    expect(datasetAgeLine(datasets, ["reactions", "analyst"], ago)).toBe("Analyst data as of 30h ago");
    expect(datasetAgeLine(datasets, ["reactions", "iv"], ago)).toBe("Earnings history as of 2h ago · last refresh step failed for Implied volatility");
    expect(datasetAgeLine(datasets, ["chains"], ago)).toBeNull();            // never succeeded: no claim
    expect(datasetAgeLine(null, ["reactions"], ago)).toBeNull();
    expect(datasetsStale(datasets, ["reactions"], 3, Date.parse("2026-10-05T09:00:00Z"))).toBe(false);
    expect(datasetsStale(datasets, ["iv"], 3, Date.parse("2026-10-05T09:00:00Z"))).toBe(true);      // a failed step is stale
    expect(datasetsStale(datasets, ["analyst"], 3, Date.parse("2026-10-09T09:00:00Z"))).toBe(true);
  });

  it("names options data by its own date and never by today", () => {
    const today = new Date().toISOString().slice(0, 10);
    expect(optionsDataPhrase("2026-09-18")).toContain("2026-09-18");
    expect(premiumSourcePhrase("2026-09-18")).toContain("2026-09-18");
    for (const text of [optionsDataPhrase(null), optionsDataPhrase(undefined), premiumSourcePhrase(null)]) {
      expect(text).not.toContain(today);
      expect(text.toLowerCase()).not.toContain("live");
    }
  });

  it("no page writes its own freshness claim", () => {
    const banned = [
      /Prices live/i, /captured live/i, /live options/i, /live chain/i, /live quote/i,
      /Chains refresh during market hours/i, /May be delayed up to 15 min/,
    ];
    for (const file of sourceFiles(SRC)) {
      if (file.endsWith("lib/freshness.ts") || file.endsWith("freshness.test.ts")) continue;
      const src = readFileSync(file, "utf8");
      for (const re of banned) expect(src, `${file} contains ${re}`).not.toMatch(re);
    }
  });

  it("every page that shows a price list renders the shared string", () => {
    for (const p of ["app/ticker-grid.tsx", "app/discover/page.tsx", "app/ivy/layout.tsx", "app/watchlist/page.tsx"]) {
      expect(readFileSync(join(SRC, p), "utf8"), p).toMatch(/freshnessLine\(|priceSourceLine\(/);
    }
  });

  it("/ivy has no always-on pulsing 'Right now' indicator", () => {
    const src = readFileSync(join(SRC, "app/ivy/page.tsx"), "utf8");
    expect(src).not.toContain("Right now");
    expect(src).not.toContain("animate-ping");
  });
});

describe("withheld price wording", () => {
  it("is null when the quote is current", () => {
    expect(priceStateLine("ok", null)).toBeNull();
    expect(priceStateLine(undefined, null)).toBeNull();
  });
  it("names the reason the API gave, which carries the last-trade date", () => {
    expect(priceStateLine("stale", "The latest price is from 2026-09-10 and is no longer current"))
      .toBe("Price unavailable. The latest price is from 2026-09-10 and is no longer current");
    expect(priceStateLine("no_data", null)).toBe("Price unavailable.");
  });
  it("dates the price from its own last-trade time, never today", () => {
    expect(priceAsOfPhrase("2026-09-10T19:59:00+00:00")).toBe("price as of 2026-09-10");
    expect(priceAsOfPhrase(null)).toBeNull();
    expect(priceAsOfPhrase("chain as of 2026-09-18")).toBeNull();
  });
});

describe("priced from the options data, the stock now from its quote (audit item 4)", () => {
  it("the Build price line names both prices by their own dates", async () => {
    const { pricedAtLine, impliedSpanPhrase, oneDayHistoryLine } = await import("@/lib/freshness");
    const fb = { current_price: 339.85, options_as_of: "2026-09-28", quote_price: 332.35, price_as_of: "2026-09-29T13:31:00+00:00" };
    expect(pricedAtLine(fb, () => "09:31:00")).toBe("priced at $339.85 from the 2026-09-28 options data; the stock is now $332.35 (last trade 09:31:00)");
    expect(pricedAtLine(fb, () => null)).toBe("priced at $339.85 from the 2026-09-28 options data; the stock is now $332.35");
    expect(pricedAtLine({ current_price: 339.85, options_as_of: "2026-09-28" }, () => "09:31:00")).toBe("priced at $339.85 from the 2026-09-28 options data");
    expect(pricedAtLine({ current_price: 339.85 }, () => null)).not.toMatch(/\d{4}-\d{2}-\d{2}/);   // no date it does not have
    // item 7: the implied move is labelled with its span, from the data; history is one-day and never counted against it
    expect(impliedSpanPhrase("2026-11-20", 53, "2026-09-28")).toBe("through 2026-11-20, 53 days from the 2026-09-28 options data");
    expect(impliedSpanPhrase("2026-11-20", 1, "2026-11-19")).toBe("through 2026-11-20, 1 day from the 2026-11-19 options data");
    expect(impliedSpanPhrase("2026-11-20", null, null)).toBe("through 2026-11-20");
    expect(impliedSpanPhrase(null, 53, "2026-09-28")).toBeNull();
    expect(oneDayHistoryLine({ avg_abs_move_pct: 0.052, max_abs_move_pct: 0.11, sample_size: 12 })).toBe("One-day earnings moves: avg ±5.2%, max ±11.0% over 12 prints");
    expect(oneDayHistoryLine({ avg_abs_move_pct: 0.052, max_abs_move_pct: 0.11, sample_size: 2 })).toBeNull();
  });

  it("the pages render those sentences and never pair the chain's spot with the quote's time or count history against the move", () => {
    const build = read("app/build/page.tsx");
    expect(build).toContain("{pricedAtLine(fb, fmtTimestamp)}");
    expect(build).toContain("pricing: pricedAtLine(fb, fmtTimestamp)");
    expect(build).toContain("impliedSpanPhrase(fb.expiration_used, fb.span_days, fb.options_as_of)");
    expect(build).not.toMatch(/current_price\.toFixed\(2\)\}<\/span>\{fmtTimestamp\(fb\.price_as_of\)/);
    expect(build).toContain("currentPrice: fb.quote_price ?? null");
    expect(read("components/PayoffSimulator.tsx")).toContain("{pricing && <p className=\"text-xs text-muted-foreground\">{symbol} {pricing}</p>}");
    const ticker = read("app/tickers/[symbol]/page.tsx");
    expect(ticker).not.toMatch(/above implied|above_expected|below_expected/);
    expect(ticker).toContain("oneDayHistoryLine(hist)");
    expect(ticker).toContain("impliedSpanPhrase(facts.expiration_used, expectedMove.span_days, facts.chain_date ?? expectedMove.chain_date)");
    expect(read("lib/api.ts")).not.toMatch(/above_expected|below_expected/);
  });
});
