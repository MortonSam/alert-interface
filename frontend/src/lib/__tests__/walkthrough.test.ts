// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, beforeEach } from "vitest";
import { PE_RANGE_ENCODING, PRICE_VS_MARKET_ENCODING, peMark, peRangeLegend, priceMark, priceVsMarketLegend, type PeMarkKey, type PriceMarkKey } from "../encodings/walkthroughCharts";
import { WALK_COPY } from "../walkthroughCopy";
import { entryLine, HOME_ENTRY, knownLine, learn, readLearned } from "../walkthrough";

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
  it("keeps the first stock a concept was learned on, and shortens the idea only on another stock", () => {
    learn("pe", "MU", "Micron");
    learn("pe", "NVDA", "NVIDIA");
    expect(readLearned().pe.symbol).toBe("MU");
    const idea = { concept: "pe", title: "P/E", text: "..." };
    const tpl = "You know {title} from {learned_from}. Here's how {name} compares.";
    expect(knownLine(tpl, idea, readLearned(), "NVDA", "NVIDIA")).toBe("You know P/E from Micron. Here's how NVIDIA compares.");
    expect(knownLine(tpl, idea, readLearned(), "MU", "Micron")).toBeNull();
    expect(knownLine(tpl, { ...idea, concept: "growth" }, readLearned(), "NVDA", "NVIDIA")).toBeNull();
  });
});
