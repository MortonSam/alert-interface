import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fmtTimestamp } from "@/lib/marks";
import { expiryCaveat } from "@/lib/optionsReadFacts";
import { EXPIRY_CAVEAT_DAYS } from "@/lib/thresholds";

const read = (p: string) => readFileSync(join(__dirname, "../..", p), "utf8");

describe("ticker page times are on the market clock", () => {
  it("Ivy's Read price time is Eastern with its date and ET, whatever the browser's zone", () => {
    expect(fmtTimestamp("2026-10-08T20:00:00+00:00")).toBe("Oct 8, 4:00 PM ET");
    expect(fmtTimestamp("chain as of 2026-09-18")).toBeNull();
  });

  it("no time on the ticker page is formatted without the New York zone", () => {
    const src = read("app/tickers/[symbol]/page.tsx");
    for (const m of src.matchAll(/toLocale(?:Time)?String\(([^)]*)\)/g)) {
      if (/hour/.test(m[1])) expect(m[1], m[0]).toContain('timeZone: "America/New_York"');
    }
    expect(src).not.toContain("timeZoneName");
    expect(src).toContain("priceLabel(facts, fmtTimestamp)");
  });
});

describe("the full-period caveat", () => {
  it("shows past the threshold with the API's sentence and not at or below it", () => {
    expect(expiryCaveat("2026-11-20", "2026-10-20")).toBe(
      "Nearest available expiration (2026-11-20) is 31 days after the 2026-10-20 earnings date. The implied move covers the full period to expiration, not just the earnings event.");
    expect(expiryCaveat("2026-10-27", "2026-10-20")).toBeNull();          // exactly EXPIRY_CAVEAT_DAYS
    expect(EXPIRY_CAVEAT_DAYS).toBe(7);
    expect(expiryCaveat("2026-11-20", null)).toBeNull();
  });

  it("the backend writes the same sentence", () => {
    const py = readFileSync(join(__dirname, "../../../../backend/app/services/implied_move.py"), "utf8");
    expect(py).toContain('f"Nearest available expiration ({str(expiration)[:10]}) is {days} days after the {str(earnings_date)[:10]} earnings date. "');
    expect(py).toContain('f"The implied move covers the full period to expiration, not just the earnings event."');
  });
});
