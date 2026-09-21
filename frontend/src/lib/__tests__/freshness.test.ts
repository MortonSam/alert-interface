import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { PRICE_FRESHNESS, freshnessLine, optionsDataPhrase, premiumSourcePhrase } from "../freshness";

const SRC = join(__dirname, "../..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return name === "__tests__" ? [] : sourceFiles(full);
    return /\.tsx?$/.test(name) ? [full] : [];
  });
}

describe("freshness wording", () => {
  it("says quotes may be delayed and never calls them live", () => {
    expect(PRICE_FRESHNESS.toLowerCase()).toContain("delayed");
    expect(freshnessLine("5h ago")).toBe(`${PRICE_FRESHNESS} · Research data refreshed nightly, last 5h ago`);
    expect(freshnessLine(null)).not.toContain("last");
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
      if (file.endsWith("lib/freshness.ts")) continue;
      const src = readFileSync(file, "utf8");
      for (const re of banned) expect(src, `${file} contains ${re}`).not.toMatch(re);
    }
  });

  it("every page that shows a price list renders the shared string", () => {
    for (const p of ["app/ticker-grid.tsx", "app/discover/page.tsx", "app/ivy/layout.tsx", "app/watchlist/page.tsx"]) {
      expect(readFileSync(join(SRC, p), "utf8"), p).toMatch(/freshnessLine\(|PRICE_FRESHNESS/);
    }
  });

  it("/ivy has no always-on pulsing 'Right now' indicator", () => {
    const src = readFileSync(join(SRC, "app/ivy/page.tsx"), "utf8");
    expect(src).not.toContain("Right now");
    expect(src).not.toContain("animate-ping");
  });
});
