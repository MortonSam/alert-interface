// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, beforeEach } from "vitest";
import { PE_RANGE_ENCODING, PRICE_VS_MARKET_ENCODING, peMark, peRangeLegend, priceMark, priceVsMarketLegend, type PeMarkKey, type PriceMarkKey } from "../encodings/walkthroughCharts";
import { WALK_COPY } from "../walkthroughCopy";
import { compareLine, entryLine, HOME_ENTRY, learn, learnedElsewhere, readLearned, type WalkFact } from "../walkthrough";

const read = (p: string) => readFileSync(join(__dirname, "../..", p), "utf8");

describe("walkthrough charts", () => {
  it("price chart: one legend row per mark, each swatch the mark it names, no two marks alike", () => {
    const keys = Object.keys(PRICE_VS_MARKET_ENCODING) as PriceMarkKey[];
    const legend = priceVsMarketLegend(keys, { name: "Micron", sector: "Information Technology" });
    expect(legend.map((l) => l.key)).toEqual(keys);
    for (const l of legend) {
      const m = priceMark(l.key as PriceMarkKey);
      expect(l.swatch.color).toBe(m.stroke);
      expect(l.swatch.dashed).toBe(m.strokeDasharray !== undefined);
      expect(l.label).not.toMatch(/\{|\}/);
    }
    const sigs = Object.values(PRICE_VS_MARKET_ENCODING).map((m) => `${m.color}|${m.dash}`);
    expect(new Set(sigs).size).toBe(sigs.length);
  });
  it("P/E chart: one legend row per mark; today is a dot, every other mark a line, no two alike", () => {
    const keys = Object.keys(PE_RANGE_ENCODING) as PeMarkKey[];
    const legend = peRangeLegend(keys, { sector: "Information Technology" });
    expect(legend.map((l) => l.key)).toEqual(keys);
    for (const l of legend) {
      expect(l.swatch.color).toBe(peMark(l.key as PeMarkKey).stroke);
      expect(l.swatch.kind).toBe(l.key === "today" ? "dot" : "line");
    }
    const sigs = Object.values(PE_RANGE_ENCODING).map((m) => `${m.color}|${m.dash}|${"dot" in m}`);
    expect(new Set(sigs).size).toBe(sigs.length);
  });
  it("the charts draw from the config and render its legend", () => {
    const src = read("components/walkthrough/WalkthroughCharts.tsx");
    expect(src).toContain("priceVsMarketLegend(");
    expect(src).toContain("peRangeLegend(");
    expect(src).not.toMatch(/stroke="hsl\(var\(--(primary|cool|foreground)\)\)"/);
  });
});

describe("walkthrough copy", () => {
  it("has no colons or em dashes in visible strings", () => {
    const strings = Object.values(WALK_COPY).map((v) => (typeof v === "function" ? (v as (...a: unknown[]) => string)("Micron", "sector") : v));
    strings.push(entryLine("Micron", 3).lead, entryLine("Micron", 3).action, HOME_ENTRY(3));
    for (const s of strings) {
      expect(s).not.toContain(":");
      expect(s).not.toContain("—");
    }
  });
  it("the entry says the stated length", () => {
    expect(`${entryLine("Micron", 3).lead} ${entryLine("Micron", 3).action}`).toBe("New to Micron? Walk through it with Ivy, about 3 minutes.");
  });
});

describe("concepts learned (this browser only)", () => {
  beforeEach(() => window.localStorage.clear());
  it("keeps the first stock a concept was learned on, and points to it only from another stock", () => {
    learn("pe", "MU", "Micron");
    learn("pe", "NVDA", "NVIDIA");
    expect(readLearned().pe.symbol).toBe("MU");
    const idea = { concept: "pe", title: "P/E", text: "..." };
    expect(learnedElsewhere(idea, readLearned(), "NVDA")).toEqual({ symbol: "MU", name: "Micron" });
    expect(learnedElsewhere(idea, readLearned(), "MU")).toBeNull();
    expect(learnedElsewhere({ ...idea, concept: "growth" }, readLearned(), "NVDA")).toBeNull();
  });
});

describe("the line comparing two stocks on a known concept", () => {
  const mu: WalkFact = { concept: "growth", measure: "sales_yoy", lead: "Micron Technology's sales grew 379.3% from a year earlier", short: "Micron Technology's grew 379.3%", tail: "in fiscal Q4 2026" };
  const o: WalkFact = { concept: "growth", measure: "sales_yoy", lead: "Realty Income's sales grew 9.7% from a year earlier", short: "Realty Income's grew 9.7%", tail: "in Q2 2026" };
  it("states both figures, each with its own period", () => {
    expect(compareLine(mu, o)).toBe("Micron Technology's sales grew 379.3% from a year earlier in fiscal Q4 2026. Realty Income's grew 9.7% in Q2 2026.");
  });
  it("names a shared period once", () => {
    const a: WalkFact = { concept: "market_vs_company", measure: "stock_1y", lead: "Micron Technology's stock rose 358.4%", short: "Micron Technology's rose 358.4%", tail: "over the year to Oct 16, 2026" };
    const b: WalkFact = { ...a, lead: "Realty Income's stock fell 0.5%", short: "Realty Income's fell 0.5%" };
    expect(compareLine(a, b)).toBe("Micron Technology's stock rose 358.4% over the year to Oct 16, 2026. Realty Income's fell 0.5%.");
  });
  it("is null (the full idea shows) when either figure is missing or the measures differ", () => {
    expect(compareLine(null, o)).toBeNull();
    expect(compareLine(mu, null)).toBeNull();
    const gross: WalkFact = { concept: "margins", measure: "gross", lead: "a", short: "b", tail: "c" };
    expect(compareLine(gross, { ...gross, measure: "operating" })).toBeNull();
  });
  it("the overlay never shows a known-concept line without both figures", () => {
    const src = read("components/walkthrough/Walkthrough.tsx");
    expect(src).not.toContain("known_concept_line");
    expect(src).toMatch(/const known = from && line \?/);
  });
});

describe("step order and the entry", () => {
  it("shows the quick check before the idea, and the idea only once the visitor answers or skips", () => {
    const src = read("components/walkthrough/Walkthrough.tsx");
    const check = src.indexOf("<QuickCheck key={step.key}");
    const idea = src.indexOf("<IdeaBox idea={step.idea}");
    expect(check).toBeGreaterThan(0);
    expect(idea).toBeGreaterThan(check);
    expect(src).toMatch(/step\.idea && \(!asks \|\| checked\) && <IdeaBox/);
    expect(src).toMatch(/setSkipped\(true\); onDone\(\);/);
    expect(src).toMatch(/setPicked\(i\); onDone\(\);/);
  });
  it("a ticker page offers the walkthrough only when the API says enough steps show data", () => {
    expect(read("components/walkthrough/WalkthroughEntry.tsx")).toMatch(/!r\.entry\) return;/);
  });
});
