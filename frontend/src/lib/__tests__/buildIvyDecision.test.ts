import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { ALTERNATIVE_FAILED, DESK_FAILED, DRAFT_FAILED, SAVE_FAILED, TRADES_FAILED, visitorMessage } from "@/lib/errors";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("the visitor always chooses the direction (Sam, 2026-11-02)", () => {
  it("Build a Trade has no Let Ivy decide and no Ivy's Pick, and drafts only the direction the visitor picked", () => {
    const src = read("app/build/page.tsx");
    for (const gone of ["Let Ivy decide", "Ivy picks from the data", "alertPick", "handleAlertPick", '"auto"', "Ivy&apos;s Pick"]) {
      expect(src, gone).not.toContain(gone);
    }
    expect(src).toContain('useState<"bullish" | "bearish" | null>(null)');
    expect(read("lib/api.ts")).not.toContain("/theses/alert-pick\"");
    expect(read("lib/api.ts")).not.toContain("alertPick:");
  });
});

describe("no exception text reaches a visitor", () => {
  it("visitorMessage shows the API's sentence and hides everything else", () => {
    expect(visitorMessage(new ApiError(429, "You've used today's 5 free drafts. Come back tomorrow."), DRAFT_FAILED))
      .toBe("You've used today's 5 free drafts. Come back tomorrow.");
    expect(visitorMessage(new ApiError(422, 'API 422: {"detail":[...]}'), DRAFT_FAILED)).toBe(DRAFT_FAILED);
    expect(visitorMessage(new TypeError("Failed to fetch"), DESK_FAILED)).toBe(DESK_FAILED);
    expect(visitorMessage(new Error("KeyError: 'strike'"), TRADES_FAILED)).toBe(TRADES_FAILED);
    expect(visitorMessage("boom", SAVE_FAILED)).toBe(SAVE_FAILED);
    for (const s of [DRAFT_FAILED, DESK_FAILED, TRADES_FAILED, ALTERNATIVE_FAILED, SAVE_FAILED]) {
      expect(s).toMatch(/\.$/);
      expect(s).not.toMatch(/error|exception|failed:|\{/i);
    }
  });

  it("Build never renders err.message", () => {
    for (const page of ["app/build/page.tsx"]) {
      const src = read(page);
      expect(src, page).not.toMatch(/err(or)?\.message/);
      expect(src, page).not.toMatch(/err instanceof Error \? err\.message/);
      expect(src, page).toContain("visitorMessage(");
    }
    const build = read("app/build/page.tsx");
    expect(build).toMatch(/setAltError\(visitorMessage\(err, ALTERNATIVE_FAILED\)\)/);   // a 429 shows the limit's own sentence
    expect(build).toContain("{altError}");
    expect(build).not.toContain("Couldn't generate an alternative");
  });
});
