import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DATE_RULES, scanDisplayedDates } from "@/lib/displayedDates";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("every displayed value carries its own date or an absence reason (home, Discover, ticker, Build)", () => {
  it("the four pages pass the source scan", () => {
    expect(scanDisplayedDates(read)).toEqual([]);
  });

  it("the scan itself catches the old patterns", () => {
    const fake = (file: string) => (file === "app/build/page.tsx" ? 'x ?? "n/a"' : file === "app/tickers/[symbol]/page.tsx" ? "today's range" : "");
    const findings = scanDisplayedDates(fake);
    expect(findings.some((f) => f.includes("absent: <reason>"))).toBe(true);
    expect(findings.some((f) => f.includes("labelled by the chain date"))).toBe(true);
    expect(DATE_RULES.length).toBeGreaterThanOrEqual(10);
  });
});
