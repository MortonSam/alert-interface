import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import NewsSections from "@/components/NewsSections";
import type { NewsSectionsResponse } from "@/lib/api";
import { fmtMovePct, moreStoriesLabel, moveTone } from "@/lib/newsSections";

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
  it("a row without Ivy's sentence shows its headline alone, with no prefix and never 'because'", () => {
    const html = renderToStaticMarkup(<NewsSections data={DATA} indexes={{ movers: "01", stories: "02" }} />);
    expect(html).toContain("Today&#x27;s biggest movers");
    expect(html).not.toContain("In the news:");
    expect(html.toLowerCase()).not.toContain("because");
    expect(html).toContain('href="https://example.com/mu" target="_blank" rel="noopener noreferrer"');
    expect(html).toContain("+3.25%");
    expect(html.indexOf(">01<")).toBeLessThan(html.indexOf(">02<"));          // the page numbers them first
    expect(fmtMovePct(-4.6158)).toBe("-4.62%");
  });
  it("each row leads with Ivy's sentence and her vine, the source story under it with 'and N more', or her exact no-news sentence", () => {
    const lead = { headline: "Micron slides as Taiwan workers authorize a strike", url: "https://example.com/strike", source: "Reuters", published_at: "2026-10-08T14:00:00Z" };
    const data: NewsSectionsResponse = {
      ...DATA,
      up: [{ ...DATA.up[0], ivy: { sentence: "No reported news explains this move.", result: "no_news", lead: null, more: 0, written_at: null } }],
      down: [{ ...DATA.down[0], ivy: { sentence: "Micron fell after Taiwan workers authorized a strike.", result: "passed", lead, more: 2, written_at: null } }],
    };
    const html = renderToStaticMarkup(<NewsSections data={data} indexes={{ movers: "01", stories: "02" }} />);
    const rows = html.split('data-testid="mover-row"').slice(1);
    expect(rows[0]).toContain("No reported news explains this move.");
    expect(rows[0]).not.toContain("<a href=\"https://");                            // no source under the no-news sentence
    expect(rows[1].indexOf("Micron fell after Taiwan workers authorized a strike.")).toBeLessThan(rows[1].indexOf("https://example.com/strike"));
    expect(rows[1]).toContain("/brand/ivy-mark.svg");
    expect(rows[1]).toContain("and 2 more");
    expect(moreStoriesLabel(0)).toBeNull();
    expect(moreStoriesLabel(1)).toBe("and 1 more");
  });
  it("print each In the news stock's change beside its ticker, in the mover rows' style and colors", () => {
    const html = renderToStaticMarkup(<NewsSections data={DATA} indexes={{ movers: "01", stories: "02" }} />);
    const changes = [...html.matchAll(/<span class="([^"]*)" data-testid="move-change">([^<]*)<\/span>/g)].map((m) => [m[1], m[2]]);
    expect(changes).toHaveLength(3);                                         // two movers and one story
    const story = html.slice(html.indexOf('data-testid="news-stories"'));
    expect(story).toContain('data-testid="move-change">-4.62%<');
    const [moverMU, storyMU] = changes.filter(([, text]) => text === "-4.62%");
    expect(storyMU[0]).toBe(moverMU[0]);                                     // the same classes as the mover row
    expect(moveTone(-1)).toBe("text-destructive");
    expect(moveTone(1)).toBe("text-success");
  });
  it("is the first thing on Discover and carries headlines only", () => {
    const page = readFileSync(join(SRC, "app/discover/page.tsx"), "utf8");
    expect(page.indexOf("<NewsSections")).toBeLessThan(page.indexOf("Ivy's Pick"));
    const comp = readFileSync(join(SRC, "components/NewsSections.tsx"), "utf8") + readFileSync(join(SRC, "lib/newsSections.ts"), "utf8");
    expect(comp).not.toMatch(/summary|because[^"]/i);
  });
});
