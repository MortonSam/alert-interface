import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Sam (2026-10-27): the ticker page teaches the company first. The tab bar and the sections read Overview, Research, Catalysts,
// Evidence, Options; nothing moves within a section.
const ORDER = ["overview", "research", "catalysts", "evidence", "options"];

describe("the ticker page's order", () => {
  const page = readFileSync(join(__dirname, "..", "..", "app", "tickers", "[symbol]", "page.tsx"), "utf8");
  it("the tab bar lists the sections in Sam's order", () => {
    const tabs = [...page.matchAll(/\{ id: "(\w+)",\s+label: "[A-Z]+" \}/g)].map((m) => m[1]);
    expect(tabs).toEqual(ORDER);
  });
  it("the sections appear on the page in the same order, Positions after Options", () => {
    const at = (id: string) => page.indexOf(id === "overview" ? '<div id="overview"' : `<section id="${id}"`);
    const positions = page.indexOf('<section id="positions"');
    const pos = ORDER.map(at);
    expect(pos.every((p) => p > 0)).toBe(true);
    expect([...pos].sort((a, b) => a - b)).toEqual(pos);
    expect(positions).toBeGreaterThan(at("options"));
  });
});
