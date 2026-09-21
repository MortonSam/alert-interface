import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { JUST_REPORTED_ENABLED } from "../features";

const SRC = join(__dirname, "../..");

describe("discover: Just reported", () => {
  const page = readFileSync(join(SRC, "app/discover/page.tsx"), "utf8");

  it("stays off while reactions need more days than the section's window", () => {
    const seeder = readFileSync(join(SRC, "../../backend/app/scripts/seed_historical_reactions.py"), "utf8");
    const minAge = Number(seeder.match(/^MIN_AGE_DAYS\s*=\s*(\d+)/m)![1]);
    const window = Number(page.match(/justReported\((\d+),/)![1]);
    if (minAge > window) expect(JUST_REPORTED_ENABLED).toBe(false);
  });

  it("is gated before it fetches or renders, and does not claim 'Notable'", () => {
    expect(page).toContain("JUST_REPORTED_ENABLED ? api.discover.justReported(");
    expect(page).toContain("{!JUST_REPORTED_ENABLED ? null :");
    expect(page).not.toContain("Notable");
  });
});
