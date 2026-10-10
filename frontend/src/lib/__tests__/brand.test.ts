import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BRAND } from "@/lib/brand";

const SRC = join(__dirname, "../..");
const PUBLIC = join(SRC, "../public");
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => { const p = join(dir, n); return statSync(p).isDirectory() ? files(p) : [p]; });
}
const sources = files(SRC).filter((p) => /\.(tsx?|css)$/.test(p) && !p.includes("__tests__"));

describe("the interim brand set", () => {
  it("every brand path points into public/brand, and every file exists", () => {
    for (const path of Object.values(BRAND)) {
      expect(path.startsWith("/brand/"), path).toBe(true);
      expect(existsSync(join(PUBLIC, path)), path).toBe(true);
    }
  });

  it("no page names a brand file directly: they go through lib/brand", () => {
    for (const p of sources.filter((p) => !p.endsWith("lib/brand.ts"))) {
      expect(readFileSync(p, "utf8"), p).not.toMatch(/\/brand\/[\w.-]+\.(svg|png|ico|webmanifest)/);
    }
  });

  it("the wordmark direction is a reference only, never on a page", () => {
    for (const p of sources) expect(readFileSync(p, "utf8"), p).not.toContain("wordmark-direction");
  });

  it("the header lockup is the heron and live text in Playfair Display", () => {
    const layout = readFileSync(join(SRC, "app/layout.tsx"), "utf8");
    expect(layout).toContain("Playfair_Display(");
    expect(layout).toMatch(/<img src=\{BRAND\.heron\}[^>]*\/>\s*<span className="font-brand[^"]*">Alert Interface<\/span>/);
    expect(BRAND.heron).toBe("/brand/heron-transparent.svg");          // the site is always dark (html.dark)
    expect(layout).toContain('<html lang="en" className={`dark ');
  });

  it("the manifest's icons are in the brand folder", () => {
    const m = JSON.parse(readFileSync(join(PUBLIC, BRAND.manifest), "utf8"));
    for (const icon of m.icons) expect(existsSync(join(PUBLIC, icon.src)), icon.src).toBe(true);
  });
});
