import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { optionsFigures } from "@/lib/optionsDetailsLine";

// NVDA on 2026-10-22, from the Oct 21 options data
const nvda = {
  totalPct: 0.0883, totalDollars: 19.65, expiration: "2026-11-20", reportPct: 0.0441, reportState: "ok",
  low: 202.32, high: 241.62, atmStrike: 222.5, chainDate: "2026-10-21",
};

describe("Options Details' paired figures", () => {
  it("are Sam's wording, verbatim, from the total and report moves", () => {
    expect(optionsFigures(nvda)).toEqual({
      total: { value: "±8.8%", sub: "$19.65 either way", label: "Options price by Nov 20, 2026" },
      report: { value: "about 4.4%", sub: "of that from the report", label: "The rest is ordinary day-to-day swing" },
      detail: "Implied range $202.32 to $241.62 · at-the-money $222.50 straddle at $19.65 · from the Oct 21, 2026 options data",
    });
  });
  it("show only the left figure when there is no report move in the window", () => {
    for (const r of [{ reportState: "no_pair" }, { reportPct: null }]) {
      const f = optionsFigures({ ...nvda, ...r });
      expect(f?.report).toBeNull();
      expect(f?.total.value).toBe("±8.8%");
    }
  });
  it("leave out what the API withheld, and show nothing without a total or its date", () => {
    const stale = optionsFigures({ ...nvda, totalDollars: null, low: null, high: null });
    expect(stale?.total.sub).toBeNull();
    expect(stale?.detail).toBe("from the Oct 21, 2026 options data");
    expect(optionsFigures({ ...nvda, totalDollars: null, low: null, high: null, chainDate: null })?.detail).toBeNull();
    expect(optionsFigures({ ...nvda, totalPct: null })).toBeNull();
    expect(optionsFigures({ ...nvda, expiration: null })).toBeNull();
  });
  it("open Details in place of the old sentence and the implied move line", () => {
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    const details = page.slice(page.indexOf('<Fold label="Details"'));
    expect(details.slice(0, 1500)).toContain("optionsFigures(");
    expect(page).not.toContain("optionsDetailsLine(");
    expect(page).not.toContain('<ExplainTip term="implied move">implied move</ExplainTip>');
    expect(page).not.toContain('text-6xl font-bold tabular-nums tracking-tight');
  });
});
