import { describe, expect, it } from "vitest";
import { SHARE_CLASS, cardEarningsNote, checkedPhrase, earningsSourceNote, eventConfirmationBadge, gridEarningsLine, nextEarningsLine, noDateLine } from "@/lib/earningsSource";

const NOW = new Date(2026, 8, 29, 10, 30);   // Sep 29, 2026, local. Checked-at stamps sit mid-day UTC so their calendar day is the same in every US zone.

describe("next earnings line", () => {
  it("prints the date, the source and when the source was last asked", () => {
    expect(nextEarningsLine("2026-10-29", "finnhub", "2026-09-29T14:05:00Z", null, null, NOW)).toBe("Next earnings Oct 29, estimated (Finnhub, checked today)");
    expect(nextEarningsLine("2026-10-28", "yfinance", "2026-09-26T14:23:16Z", null, null, NOW)).toBe("Next earnings Oct 28, estimated (Yahoo Finance, checked 3 days ago)");
  });
  it("a missing date still says when it was checked, and an unchecked ticker says so", () => {
    expect(nextEarningsLine(null, null, "2026-09-29T14:05:00Z", null, null, NOW)).toBe("No confirmed date yet (Finnhub, checked Sep 29)");
    expect(nextEarningsLine(null, null, null, null, null, NOW)).toBe("No confirmed date yet (not yet checked)");
    expect(nextEarningsLine("2026-12-09", "finnhub", null, null, null, NOW)).toBe("Next earnings Dec 9, estimated (Finnhub, not yet checked)");
  });
  it("checked phrases are calendar days, not 24-hour windows", () => {
    expect(checkedPhrase("2026-09-28T23:59:00", NOW)).toBe("checked yesterday");
    expect(checkedPhrase("2026-09-29T00:01:00", NOW)).toBe("checked today");
    expect(checkedPhrase("garbage", NOW)).toBe("not yet checked");
  });
  it("the Discover note is the short form", () => {
    expect(earningsSourceNote("finnhub", "2026-09-29T14:05:00Z", NOW)).toBe("Finnhub, checked today");
    expect(earningsSourceNote(null, null, NOW)).toBe("not yet checked");
  });
});

describe("a ticker the calendar left without a date is never blank", () => {
  it("says so with the source and the check date, everywhere the date would show", () => {
    expect(noDateLine("2026-09-28T14:05:00Z")).toBe("No confirmed date yet (Finnhub, checked Sep 28)");
    expect(cardEarningsNote(null, null, "2026-09-29T14:05:00Z", null, null, NOW)).toBe("No confirmed date yet (Finnhub, checked Sep 29)");
    expect(cardEarningsNote("2026-10-29", "finnhub", "2026-09-29T14:05:00Z", null, null, NOW)).toBe("Earnings Oct 29, estimated \u00B7 Finnhub, checked today");
  });
  it("the ticker grid, Build fact grid and Discover rows render the no-date line from the API fields", () => {
    const { readFileSync } = require("node:fs") as typeof import("node:fs");
    const { join } = require("node:path") as typeof import("node:path");
    const src = join(__dirname, "../..");
    const grid = readFileSync(join(src, "app/ticker-grid.tsx"), "utf8");
    expect(grid).toContain("gridEarningsLine(ticker.next_earnings_date, ticker.next_earnings_confirmation)");   // date and status only
    expect(grid).not.toMatch(/\{ticker\.next_earnings_date && \(/);
    expect(grid).not.toMatch(/cardEarningsNote|noDateLine|checked/);
    expect(gridEarningsLine("2026-10-29", "estimated")).toBe("Earnings Oct 29, estimated");
    expect(gridEarningsLine("2026-10-29", "expected_unconfirmed")).toBe("Earnings Oct 29, estimated");
    expect(gridEarningsLine("2026-10-01", "confirmed")).toBe("Earnings Oct 1, confirmed");
    expect(gridEarningsLine(null, null)).toBe("No confirmed date yet");
    expect([SHARE_CLASS.GOOGL, SHARE_CLASS.GOOG, SHARE_CLASS.FOXA, SHARE_CLASS.FOX, SHARE_CLASS.NWSA, SHARE_CLASS.NWS]).toEqual(["Class A", "Class C", "Class A", "Class B", "Class A", "Class B"]);
    const build = readFileSync(join(src, "app/build/page.tsx"), "utf8");
    expect(build).toMatch(/fb\.earnings_date \? cardEarningsNote\([\s\S]{0,200}: noDateLine\(fb\.earnings_checked_at\)/);
    expect(build).not.toContain('fb.earnings_date ?? "n/a"');
    const discover = readFileSync(join(src, "lib/discoverSentences.ts"), "utf8");
    expect((discover.match(/earningsClause\(item\.earnings_date, item\.earnings_source, item\.earnings_checked_at, item\.earnings_confirmation, item\.earnings_note, now\)/g) || []).length).toBe(2);
    expect(discover).toContain("if (!date) return noDateClause(checkedAt, now);");
  });
});

describe("confirmation levels, NKE on 2026-09-29", () => {
  const CHECKED = "2026-09-29T16:02:47Z";
  it("an estimate that passed unresolved reads 'expected around', never past", () => {
    expect(nextEarningsLine("2026-09-28", "finnhub", CHECKED, "expected_unconfirmed", "expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR", NOW))
      .toBe("Next earnings expected around Sep 28; not confirmed (checked today)");
    expect(eventConfirmationBadge({ is_confirmed: false, unresolved_since: "2026-09-29", source: "finnhub" })).toBe("Expected, date not confirmed");
  });
  it("the resolved NKE header is Yahoo's Oct 1 estimate, and a confirmed date says what confirmed it", () => {
    expect(nextEarningsLine("2026-10-01", "yfinance", CHECKED, "estimated", "estimated (Yahoo Finance); Finnhub says 2026-09-28", NOW))
      .toBe("Next earnings Oct 1, estimated (Yahoo Finance, checked today)");
    expect(nextEarningsLine("2026-10-01", "edgar", CHECKED, "confirmed", "confirmed: press release via Finnhub news 2026-08-28: NIKE, Inc. to Announce First Quarter Fiscal 2027 Results", NOW))
      .toBe("Next earnings Oct 1, confirmed (press release via Finnhub news 2026-08-28: NIKE, Inc. to Announce First Quarter Fiscal 2027 Results; checked today)");
    expect(nextEarningsLine("2026-10-29", "finnhub", CHECKED, "confirmed", "confirmed: Finnhub and Yahoo Finance agree", NOW))
      .toBe("Next earnings Oct 29, confirmed (Finnhub and Yahoo Finance agree; checked today)");
    expect(eventConfirmationBadge({ is_confirmed: true, source: "finnhub" })).toBe("Confirmed");
    expect(eventConfirmationBadge({ is_confirmed: false, source: "yfinance" })).toBe("Estimated (Yahoo Finance)");
  });
  it("cards carry the level too", () => {
    expect(cardEarningsNote("2026-09-28", "finnhub", CHECKED, "expected_unconfirmed", null, NOW)).toBe("Earnings expected around Sep 28; not confirmed");
    expect(cardEarningsNote("2026-10-01", "yfinance", CHECKED, "confirmed", "confirmed: Finnhub and Yahoo Finance agree", NOW)).toBe("Earnings Oct 1, confirmed (Finnhub and Yahoo Finance agree)");
  });
  it("the Catalysts hero shows Past only with a reaction row or a confirmed event", () => {
    const { readFileSync } = require("node:fs") as typeof import("node:fs");
    const { join } = require("node:path") as typeof import("node:path");
    const page = readFileSync(join(__dirname, "../..", "app/tickers/[symbol]/page.tsx"), "utf8");
    expect(page).toMatch(/pastHasReport = isPast && !!displayEvent && \(displayEvent\.is_confirmed \|\| reactions\.some/);
    expect(page).toMatch(/\{isPast && pastHasReport && \([\s\S]{0,200}Past/);
    expect(page).toContain("eventConfirmationBadge(displayEvent)");
    for (const f of ["app/ticker-grid.tsx", "app/build/page.tsx"]) {
      expect(readFileSync(join(__dirname, "../..", f), "utf8")).toMatch(/next_earnings_confirmation|earnings_confirmation/);
    }
  });
});
