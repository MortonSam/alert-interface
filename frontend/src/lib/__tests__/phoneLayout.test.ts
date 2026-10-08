import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("the home page on a phone", () => {
  it("no section is a full screen below 640px, and the padding keeps gaps near 96px", () => {
    const home = read("app/page.tsx") + read("components/LatestVerifiedNote.tsx");
    const sections = home.match(/<section className="[^"]*"/g) ?? [];
    expect(sections.length).toBeGreaterThanOrEqual(7);
    for (const s of sections.slice(1)) {
      expect(s, s).not.toMatch(/(^|[" ])min-h-\[100svh\]/);           // a full screen only from sm up
      expect(s, s).not.toMatch(/(^|[" ])py-(2[0-9]|1[3-9])\b/);         // phone padding at most py-12 (48px a side)
    }
  });
  it("the hero is the screen below the header on a phone, so the scroll cue sits at its bottom", () => {
    expect(read("app/page.tsx")).toContain('<section className="min-h-[calc(100svh-3.25rem-1px)] sm:min-h-[100svh] flex flex-col bg-background">');
  });
  it("the header is one row: the logo, a menu button for the five links, and the search icon", () => {
    const nav = read("components/NavLinks.tsx");
    expect(nav).toContain('<div className="hidden sm:contents">{links(false)}</div>');
    expect(nav).toContain('className="sm:hidden" data-testid="phone-menu"');
    expect(nav).toMatch(/aria-label=\{open \? "Close menu" : "Open menu"\}/);
  });
  it("stock cards wrap the sector name on a phone; the PostHog toolbar tab is hidden below 640px", () => {
    expect(read("app/ticker-grid.tsx")).toContain('<span className="min-w-0 break-words sm:line-clamp-1">{ticker.sector}</span>');
    expect(read("app/ticker-grid.tsx")).toContain('text-xs font-medium text-foreground/70 [overflow-wrap:anywhere]');   // a long note or URL never widens the page
    expect(read("app/globals.css")).toMatch(/@media \(max-width: 639px\) \{\s*#__POSTHOG_TOOLBAR__ \{ display: none !important; \}/);
  });
});
