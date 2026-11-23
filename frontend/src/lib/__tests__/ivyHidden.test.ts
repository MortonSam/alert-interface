import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";
import { NAV_LINKS } from "@/components/NavLinks";

const SRC = join(__dirname, "../..");

// Sam, 2026-11-23: Ivy is out of the top navigation and the home page for every visitor; the /ivy pages stay, reachable by URL
describe("Ivy is reachable by URL only", () => {
  it("the top navigation and the home page do not link to /ivy", () => {
    expect(NAV_LINKS.map((l) => l.href)).not.toContain("/ivy");
    expect(readFileSync(join(SRC, "app/page.tsx"), "utf8")).not.toMatch(/href="\/ivy/);
  });
  it("the /ivy pages are still there", () => {
    for (const p of ["app/ivy/page.tsx", "app/ivy/desk/page.tsx", "app/ivy/trades/page.tsx"]) expect(existsSync(join(SRC, p))).toBe(true);
  });
});
