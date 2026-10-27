import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Sam (2026-10-27): Recent News is the last thing on the ticker page, after Options and Your Positions, and while company news is
// withheld (PERSONAL_USE_DATA_SHOWN off) there is no news block at all: never "No recent news in the last 48 hours" for withheld news.
describe("the ticker page's news block", () => {
  const page = readFileSync(join(__dirname, "..", "..", "app", "tickers", "[symbol]", "page.tsx"), "utf8");
  const news = page.indexOf("── RECENT NEWS");
  it("comes after Options and Your Positions, and outside Research", () => {
    expect(news).toBeGreaterThan(page.indexOf('<section id="options"'));
    expect(news).toBeGreaterThan(page.indexOf('<section id="positions"'));
    const research = page.indexOf('<section id="research"');
    expect(page.slice(research, page.indexOf('<section id="catalysts"'))).not.toContain("Recent News");
  });
  it("is hidden while news is withheld, and a source that could not be asked is never no news", () => {
    expect(page).toContain('setNewsStatus(data.state === "withheld" ? "withheld" : data.state === "unavailable" ? "error"');
    expect(page.slice(news)).toMatch(/^[^\n]*\n\s*\{newsStatus !== "withheld" && newsStatus !== "loading" && \(/);
  });
});
