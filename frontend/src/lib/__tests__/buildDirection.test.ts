import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("Build a Trade shows direction as a plain text label", () => {
  it("no bull or bear icon renders anywhere in the app", () => {
    const files = ["app/build/page.tsx", "app/theses/page.tsx", "app/theses/[id]/page.tsx", "app/ivy/trades/page.tsx", "app/ivy/desk/page.tsx", "app/discover/page.tsx"];
    for (const f of files) {
      const src = read(f);
      expect(src, f).not.toMatch(/GiBull|GiBearFace|react-icons\/gi|🐂|🐻/);
    }
  });
  it("the direction picker labels are the site's text, with no icon in their place", () => {
    const src = read("app/build/page.tsx");
    const bullish = src.indexOf('<div className="text-base font-bold">Bullish</div>');
    const bearish = src.indexOf('<div className="text-base font-bold">Bearish</div>');
    expect(bullish).toBeGreaterThan(0);
    expect(bearish).toBeGreaterThan(0);
    // the label is the first child of its button: nothing (icon, svg, emoji) precedes it
    for (const idx of [bullish, bearish]) {
      const before = src.slice(src.lastIndexOf(">", idx - 1) - 200, idx);
      expect(before).not.toMatch(/<svg|<Gi|<Hi|aria-hidden/);
    }
  });
});
