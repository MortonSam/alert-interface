// The Intrinio attribution (an Order Form condition, 2026-10-14): "Market data from Intrinio" linked to https://intrinio.com in the
// one sitewide footer every route inherits, as a followed link.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { MARKET_DATA_CREDIT } from "@/lib/brand";

const SRC = join(__dirname, "..", "..");
const layout = readFileSync(join(SRC, "app", "layout.tsx"), "utf8");
const anchor = layout.match(/<a\b[^>]*MARKET_DATA_CREDIT\.href[^>]*>/)?.[0] ?? "";

describe("the market-data credit", () => {
  it("names Intrinio and links its site", () => {
    expect(MARKET_DATA_CREDIT.text).toBe("Market data from Intrinio");
    expect(MARKET_DATA_CREDIT.href).toBe("https://intrinio.com");
    expect(layout).toContain("{MARKET_DATA_CREDIT.text}");
    expect(anchor).toContain("href={MARKET_DATA_CREDIT.href}");
  });

  it("is a followed link: no nofollow, ugc or sponsored", () => {
    expect(anchor).toContain("rel={MARKET_DATA_CREDIT.rel}");
    const rels = MARKET_DATA_CREDIT.rel.split(/\s+/);
    for (const banned of ["nofollow", "ugc", "sponsored"]) expect(rels).not.toContain(banned);
    expect(rels).toEqual(["noopener"]);
    expect(anchor).not.toMatch(/nofollow|ugc|sponsored/);
  });

  it("sits in the root layout's footer, and no route renders a footer of its own", () => {
    const footer = layout.slice(layout.indexOf("<footer"), layout.indexOf("</footer>"));
    expect(footer).toContain("MARKET_DATA_CREDIT.text");
    const walk = (d: string): string[] => readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(d, e.name)) : [join(d, e.name)]));
    const routeFiles = walk(join(SRC, "app")).filter((f) => /(layout|page|not-found)\.tsx$/.test(f) && !f.endsWith(join("app", "layout.tsx")));
    expect(routeFiles.length).toBeGreaterThan(10);
    for (const f of routeFiles) expect(readFileSync(f, "utf8"), f).not.toMatch(/<footer\b/);
  });
});
