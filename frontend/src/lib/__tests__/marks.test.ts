import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { MARK_BASIS_LABELS, fmtTimestamp, markBasisLabel, optionsAsOfLabel } from "../marks";

describe("option mark labels", () => {
  it("has a label for every mark_basis the backend can send", () => {
    const schema = readFileSync(join(__dirname, "../../../../backend/app/schemas/thesis.py"), "utf8");
    const tuple = schema.match(/MARK_BASES\s*=\s*\(([^)]*)\)/);
    expect(tuple, "MARK_BASES not found in backend schema").not.toBeNull();
    const bases = [...tuple![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(bases.length).toBeGreaterThanOrEqual(5);
    for (const b of bases) expect(Object.keys(MARK_BASIS_LABELS), `no label for ${b}`).toContain(b);
    expect(Object.keys(MARK_BASIS_LABELS).sort()).toEqual([...bases].sort());
  });

  it("never calls stored daily data live", () => {
    for (const label of Object.values(MARK_BASIS_LABELS)) expect(label.toLowerCase()).not.toContain("live");
    expect(markBasisLabel("something_new")).toBe("mark basis unknown");
  });

  it("cannot render Invalid Date", () => {
    expect(fmtTimestamp("chain as of 2026-09-18")).toBeNull();   // the prose the API used to send
    expect(fmtTimestamp("")).toBeNull();
    expect(fmtTimestamp(null)).toBeNull();
    const ok = fmtTimestamp("2026-09-21T17:59:47+00:00", new Date("2026-09-21T18:30:00+00:00"));
    expect(ok).not.toBeNull();
    expect(ok).not.toContain("Invalid");
  });

  it("labels the options date from its own field", () => {
    expect(optionsAsOfLabel({ mark_basis: "ingested_chain", chain_date: "2026-09-18" })).toBe("options data as of 2026-09-18");
    expect(optionsAsOfLabel({ mark_basis: "settled", options_as_of: "2026-09-19" })).toBe("settled 2026-09-19");
    expect(optionsAsOfLabel({ mark_basis: "not_found", chain_date: null })).toBe("");
  });

  it("no thesis page parses a date out of as_of prose or names a live chain", () => {
    for (const p of ["app/theses/page.tsx", "app/theses/[id]/page.tsx"]) {
      const src = readFileSync(join(__dirname, "../..", p), "utf8");
      expect(src, p).not.toContain('"live_chain"');
      expect(src, p).not.toMatch(/new Date\(\s*(mark|m)\??\.as_of/);
    }
  });
});

import { ivDisclosure, type Leg } from "../black-scholes";

describe("simulator IV disclosure", () => {
  const leg = (over: Partial<Leg>): Leg => ({ kind: "call", K: 150, mid: 4, sigma: 0.312, ivSource: "strike", dir: 1, label: "Long $150 call", ...over });

  it("says which IV a single leg uses", () => {
    expect(ivDisclosure([leg({})])).toBe("31.2% (this strike's IV)");
    expect(ivDisclosure([leg({ ivSource: "atm" })])).toBe("31.2% (at-the-money IV)");
    expect(ivDisclosure([leg({ sigma: 0.3, ivSource: "default" })])).toBe("30.0% (30% default, no IV available)");
  });

  it("labels every leg of a spread, so a shared ATM IV is not presented as per-strike", () => {
    const text = ivDisclosure([leg({ ivSource: "atm" }), leg({ K: 155, dir: -1, label: "Short $155 call", ivSource: "atm" })]);
    expect(text).toBe("Long $150 call: 31.2% (at-the-money IV) · Short $155 call: 31.2% (at-the-money IV)");
  });

  it("the thesis page asks strategy-data for the thesis's own expiration", () => {
    const src = readFileSync(join(__dirname, "../../app/theses/[id]/page.tsx"), "utf8");
    expect(src).toContain("api.tickers.strategyData(t.ticker_symbol, t.option_expiration)");
  });
});
