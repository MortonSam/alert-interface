import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("the preview page", () => {
  it("stores a pasted token in this browser only, is not indexed, and carries no token", () => {
    const page = read("app/preview/page.tsx");
    const client = read("app/preview/PreviewToken.tsx");
    expect(page).toContain("robots: { index: false, follow: false }");
    expect(client).toContain('localStorage.setItem(KEY, t)');
    expect(client).toContain('history.replaceState(null, "", window.location.pathname)');   // a #t= token leaves the address bar at once
    expect(client).toContain('type="password"');
    expect(page + client).not.toMatch(/[A-Za-z0-9_-]{24,}/);                                  // no token-like literal in the source
  });
});
