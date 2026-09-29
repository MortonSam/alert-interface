import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("Build a Trade direction picker", () => {
  it("shows a bull icon above Bullish and a bear icon above Bearish, decorative, with the text label as the name", () => {
    const src = read("app/build/page.tsx");
    expect(src).toContain('import { GiBull, GiBearFace } from "react-icons/gi";');
    const bullish = src.indexOf('<div className="text-base font-bold">Bullish</div>');
    const bearish = src.indexOf('<div className="text-base font-bold">Bearish</div>');
    expect(bullish).toBeGreaterThan(0);
    expect(bearish).toBeGreaterThan(0);
    // the icon is the child just before its label, hidden from assistive tech: the label is what is read
    expect(src.slice(bullish - 120, bullish)).toMatch(/<GiBull aria-hidden="true"[^>]*\/>\s*$/);
    expect(src.slice(bearish - 120, bearish)).toMatch(/<GiBearFace aria-hidden="true"[^>]*\/>\s*$/);
  });
  it("no other direction view renders the icons: cards, saved summary, theses and Ivy trades print direction as text", () => {
    const files = ["app/theses/page.tsx", "app/theses/[id]/page.tsx", "app/ivy/trades/page.tsx", "app/ivy/desk/page.tsx", "app/discover/page.tsx"];
    for (const f of files) {
      expect(read(f), f).not.toMatch(/GiBull|GiBearFace|react-icons\/gi|🐂|🐻/);
    }
  });
});
