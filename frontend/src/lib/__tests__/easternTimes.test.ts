import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fmtTimestamp } from "@/lib/marks";
import { expiryCaveat, namedReportDate } from "@/lib/optionsReadFacts";
import { EXPIRY_CAVEAT_DAYS } from "@/lib/thresholds";

const read = (p: string) => readFileSync(join(__dirname, "../..", p), "utf8");

describe("ticker page times are on the market clock", () => {
  it("Ivy's Read price time is Eastern with its date and ET, whatever the browser's zone", () => {
    expect(fmtTimestamp("2026-10-08T20:00:00+00:00")).toBe("Oct 8, 2026, 4:00 PM ET");
    expect(fmtTimestamp("chain as of Sep 18, 2026")).toBeNull();
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
      "Nearest available expiration (Nov 20, 2026) is 31 days after the Oct 20, 2026 earnings date. The implied move covers the full period to expiration, not just the earnings event.");
    expect(expiryCaveat("2026-10-27", "2026-10-20")).toBeNull();          // exactly EXPIRY_CAVEAT_DAYS
    expect(EXPIRY_CAVEAT_DAYS).toBe(7);
    expect(expiryCaveat("2026-11-20", null)).toBeNull();
  });

  it("names a report date only when it is the date the header shows (JNJ, 2026-11-12: a vendor's Jan 26 under a header that said around Jan 20)", () => {
    expect(namedReportDate("2027-01-26", null)).toBeNull();                // the company has not confirmed a date: the header shows a window
    expect(namedReportDate("2027-01-26", "2027-01-28")).toBeNull();        // the header shows another day
    expect(namedReportDate("2026-11-18", "2026-11-18T00:00:00Z")).toBe("2026-11-18");
    expect(namedReportDate(null, "2026-11-18")).toBeNull();
    expect(expiryCaveat("2027-03-19", namedReportDate("2027-01-26", null))).toBeNull();
    const page = read("app/tickers/[symbol]/page.tsx");
    expect(page.match(/expiryCaveat\(/g)?.length).toBe(2);
    expect(page.match(/expiryCaveat\(facts\.expiration_used, namedReportDate\(facts\.next_earnings_date, ticker\.next_earnings_date\)\)/g)?.length).toBe(2);
    const py = readFileSync(join(__dirname, "../../../../backend/app/routers/tickers.py"), "utf8");
    expect(py).not.toContain("expiry_caveat(chosen_exp, earnings_str)");   // the API's own note follows the same rule
  });

  it("the backend writes the same sentence", () => {
    const py = readFileSync(join(__dirname, "../../../../backend/app/services/implied_move.py"), "utf8");
    expect(py).toContain('f"Nearest available expiration ({fmt_day(expiration)}) is {days} days after the {fmt_day(earnings_date)} earnings date. "');
    const dates = readFileSync(join(__dirname, "../../../../backend/app/services/dates.py"), "utf8");
    expect(dates).toContain('return d.strftime("%b %-d, %Y")');             // the same "Nov 20, 2026" lib/dates.fmtDate writes
    expect(py).toContain('f"The implied move covers the full period to expiration, not just the earnings event."');
  });
});
