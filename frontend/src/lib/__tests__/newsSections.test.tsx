import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import NewsSections from "@/components/NewsSections";
import type { NewsSectionsResponse } from "@/lib/api";
import { NEWS_LABEL, fmtMovePct } from "@/lib/newsSections";

const SRC = join(__dirname, "../..");
const H = { headline: "Micron Could Be Poised for a Major Breakout", url: "https://example.com/mu", source: "Yahoo", published_at: "2026-10-08T15:20:00Z" };
const DATA: NewsSectionsResponse = {
  visible: true, reason: null, quotes_as_of: "2026-10-08T17:53:05Z",
  up: [{ symbol: "HD", name: "The Home Depot, Inc.", price: 295.06, change_pct: 3.2509, quote_time: "2026-10-08T17:53:05Z", headline: null }],
  down: [{ symbol: "MU", name: "Micron Technology, Inc.", price: 1037.78, change_pct: -4.6158, quote_time: "2026-10-08T17:53:05Z", headline: H }],
  stories: [{ ...H, symbol: "MU", change_pct: -4.6158 }],
};

describe("Discover news sections", () => {
  it("render nothing when the API fails closed or the flag is off", () => {
    expect(renderToStaticMarkup(<NewsSections data={null} indexes={{ movers: "01", stories: "02" }} />)).toBe("");
    expect(renderToStaticMarkup(<NewsSections data={{ ...DATA, visible: false, reason: "the newest story is more than 24 hours old" }} indexes={{ movers: "01", stories: "02" }} />)).toBe("");
  });
  it("label a headline beside a move 'In the news:', never 'because', and a mover with no headline shows none", () => {
    const html = renderToStaticMarkup(<NewsSections data={DATA} indexes={{ movers: "01", stories: "02" }} />);
    expect(html).toContain("Today&#x27;s biggest movers");
    expect(html).toContain(`${NEWS_LABEL} `);
    expect(html.match(/In the news:/g)?.length).toBe(1);                       // MU has a headline; HD has none, so no label
    expect(html.toLowerCase()).not.toContain("because");
    expect(html).toContain('href="https://example.com/mu" target="_blank" rel="noopener noreferrer"');
    expect(html).toContain("+3.25%");
    expect(html.indexOf(">01<")).toBeLessThan(html.indexOf(">02<"));          // the page numbers them first
    expect(fmtMovePct(-4.6158)).toBe("-4.62%");
  });
  it("is the first thing on Discover and carries headlines only", () => {
    const page = readFileSync(join(SRC, "app/discover/page.tsx"), "utf8");
    expect(page.indexOf("<NewsSections")).toBeLessThan(page.indexOf("Ivy's Pick"));
    const comp = readFileSync(join(SRC, "components/NewsSections.tsx"), "utf8") + readFileSync(join(SRC, "lib/newsSections.ts"), "utf8");
    expect(comp).not.toMatch(/summary|because[^"]/i);
  });
});
