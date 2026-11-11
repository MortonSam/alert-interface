// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, beforeEach } from "vitest";
import { PE_RANGE_ENCODING, PRICE_VS_MARKET_ENCODING, peMark, peRangeLegend, priceMark, priceVsMarketLegend, type PeMarkKey, type PriceMarkKey } from "../encodings/walkthroughCharts";
import { WALK_COPY } from "../walkthroughCopy";
import { compareLine, researchEntry, HOME_ENTRY, learn, learnedElsewhere, readLearned, type WalkFact } from "../walkthrough";

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
    const legend = peRangeLegend(keys, { sector: "Information Technology", median: "Its median since Oct 20, 2023" });
    expect(legend.map((l) => l.key)).toEqual(keys);
    for (const l of legend) {
      expect(l.swatch.color).toBe(peMark(l.key as PeMarkKey).stroke);
      expect(l.swatch.kind).toBe(l.key === "today" ? "dot" : "line");
      expect(l.label).not.toMatch(/\{|\}/);
    }
    // the median's name is the API's, by the window it covers; the page never types "five-year" itself (Sam, 2026-11-10)
    expect(legend.find((l) => l.key === "median")?.label).toBe("Its median since Oct 20, 2023");
    expect(peRangeLegend(["median"], { sector: null })[0].label).toBe("Its median");
    expect(JSON.stringify(PE_RANGE_ENCODING)).not.toMatch(/five/i);
    expect(read("components/walkthrough/WalkthroughCharts.tsx")).toContain("median: chart.median_label");
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
    strings.push(researchEntry("Micron", 3).action, researchEntry("Micron", 3).length, HOME_ENTRY(3));
    for (const s of strings) {
      expect(s).not.toContain(":");
      expect(s).not.toContain("—");
    }
  });
  it("the entry says the stated length", () => {
    expect(researchEntry("Micron", 3)).toEqual({ action: "Walk through Micron with Ivy", length: "About 3 minutes" });
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

describe("a check whose answer is the same for every stock", () => {
  beforeEach(() => window.localStorage.clear());
  it("is asked only until the visitor has met that answer for the concept", async () => {
    const { alreadyMet } = await import("../walkthrough");
    const check = { concept: "report_move", question: "q", options: ["a"], answer: 0, why: "w", same_answer: "report_move" };
    expect(alreadyMet(check, readLearned())).toBe(false);
    learn("report_move", "TSLA", "Tesla", new Date(), "report_move");
    expect(alreadyMet(check, readLearned())).toBe(true);
    const faster = { ...check, concept: "growth", same_answer: "growth:faster" };
    learn("growth", "MU", "Micron", new Date(), "growth:slower");
    expect(alreadyMet(faster, readLearned())).toBe(false);                 // the direction differs from the last one met
    learn("growth", "AAPL", "Apple", new Date(), "growth:faster");
    expect(alreadyMet(faster, readLearned())).toBe(true);
    expect(readLearned().growth.symbol).toBe("MU");                         // still the stock it was first learned on
    expect(alreadyMet({ ...check, same_answer: undefined }, readLearned())).toBe(false);
  });
  it("the comparison line reads with an empty period", () => {
    const t: WalkFact = { concept: "report_move", measure: "report_multiple", lead: "Tesla's report days swing 4.1 times an ordinary day", short: "Tesla's swing 4.1 times", tail: "" };
    const m: WalkFact = { ...t, lead: "Micron Technology's report days swing 1.7 times an ordinary day", short: "Micron Technology's swing 1.7 times" };
    expect(compareLine(t, m)).toBe("Tesla's report days swing 4.1 times an ordinary day. Micron Technology's swing 1.7 times.");
  });
});

describe("known-concept label", () => {
  it("names the walkthrough the visitor met the idea in, in the possessive", () => {
    expect(WALK_COPY.knownFrom("NVIDIA")).toBe("You saw this idea in NVIDIA's walkthrough");
    expect(WALK_COPY.knownFrom("Micron Technology")).toBe("You saw this idea in Micron Technology's walkthrough");
    expect(WALK_COPY.knownFrom("Ross Stores")).toBe("You saw this idea in Ross Stores' walkthrough");
    expect(WALK_COPY.knownFrom("Lowe's")).toBe("You saw this idea in Lowe's walkthrough");
  });
});
