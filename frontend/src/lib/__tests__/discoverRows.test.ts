import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { JustReportedItem, LatestPickItem, ReportingSoonItem, SuggestionItem, UnusuallyActiveItem, EarningsOutcome } from "@/lib/api";
import {
  CONFIRMED_KIND,
  OUTCOME_LEAD,
  confirmedKind,
  earningsClause,
  justReportedSentence,
  latestPickSentence,
  noDateClause,
  reportingSoonSentence,
  suggestionSentence,
  tapeReceipt,
  unusuallyActiveSentence,
} from "@/lib/discoverSentences";
import { DISCOVER_ELEVATED_RV, TAPE_CHOPPIEST_RANK, TAPE_ONE_OF_CHOPPIEST_RANK, TAPE_OPTIONS_BAND_PP } from "@/lib/thresholds";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

const NOW = new Date(2026, 8, 29, 10, 30);          // Sep 29, 2026, local
const TODAY_CHECK = "2026-09-29T06:00:00";           // local, same calendar day as NOW

const base = { name: "Acme Corp", sector: "Industrials", industry: "Machinery" };

describe("Discover is a list of rows, not a card grid", () => {
  const page = read("app/discover/page.tsx");
  const row = read("components/DiscoverRow.tsx");

  it("the card grid, its card and its pills are gone", () => {
    expect(page).not.toMatch(/grid-cols-1 sm:grid-cols-2 lg:grid-cols-4/);
    expect(page).not.toMatch(/lg:grid-cols-\d/);
    expect(page).not.toContain("DiscoverCard");
    expect(page).not.toContain("rounded-full");
    expect(existsSync(join(SRC, "components/DiscoverCard.tsx"))).toBe(false);
  });

  it("every section renders the row template with its own sentence", () => {
    expect(page).toContain('import DiscoverRow, { DiscoverRows } from "@/components/DiscoverRow";');
    for (const fn of ["latestPickSentence(latestPick)", "reportingSoonSentence(item)", "justReportedSentence(item)", "suggestionSentence(item)", "unusuallyActiveSentence(item)"]) {
      expect(page).toContain(`sentence={${fn}}`);
    }
    expect(page.match(/<DiscoverRow\b/g)?.length).toBe(5);
    expect(page.match(/<DiscoverRows>/g)?.length).toBe(6);   // five sections and the loading skeleton
  });

  it("a row is one link to the ticker page, one column with a hairline between rows, and nothing truncates", () => {
    expect(row).toContain("href={`/tickers/${symbol}`}");
    expect(row).toContain('<ul className="divide-y divide-border/60">');
    expect(row).toContain("font-bold");
    for (const src of [page, row]) {
      expect(src).not.toMatch(/\btruncate\b|line-clamp|text-ellipsis|whitespace-nowrap/);
      expect(src).not.toMatch(/…|\.\.\."/);
    }
  });

  it("keeps the freshness line and numbers sections as they render", () => {
    expect(page).toContain("freshnessLine(datasetAgeLine(health?.datasets, DISCOVER_DATASETS, timeAgo), health?.cadence)");
    expect(page).not.toContain("health.last_refreshed_at");            // the global stamp dates nothing a visitor sees
    expect(page.match(/index=\{nextIndex\(\)\}/g)?.length).toBe(5);
    expect(page).toContain('<div className="max-w-6xl mx-auto">');
  });
});

describe("row sentences", () => {
  it("the calendar: when, the level with its source in parentheses, then the stored blurb", () => {
    const item: ReportingSoonItem = {
      ...base, symbol: "ACME", earnings_date: "2026-09-30", is_confirmed: true, source: "finnhub",
      checked_at: TODAY_CHECK, confirmation: "confirmed",
      confirmation_note: "confirmed: press release via Finnhub news 2026-09-02: Acme Corp to Announce Fiscal 2027 First Quarter Results",
      insight: "Beat 7 of 8, averaging +3.1% on the 1-day reaction to a beat", vol_regime: "iv_rich",
    };
    expect(reportingSoonSentence(item, NOW)).toBe(
      "Reports tomorrow (confirmed, company press release); beat 7 of 8, averaging +3.1% on the 1-day reaction to a beat");     // no IV rich/cheap on the calendar

    const estimated = { ...item, earnings_date: "2026-10-02", confirmation: "estimated", confirmation_note: null, insight: null, vol_regime: null };
    expect(reportingSoonSentence(estimated, NOW)).toBe("Reports in 3 days (estimated, Finnhub, checked today)");

    const today = { ...estimated, earnings_date: "2026-09-29", confirmation: "expected_unconfirmed", source: "yfinance", vol_regime: "iv_fair" };
    expect(reportingSoonSentence(today, NOW)).toBe("Expected to report today (not confirmed, Yahoo Finance, checked today)");
  });

  it("a confirmed date names its source type, never the headline or the announcement date", () => {
    const headline = "confirmed: press release via Finnhub news 2026-09-02: Acme Corp to Announce Fiscal 2027 First Quarter Results";
    const filing = "confirmed: 8-K Item 8.01 filed 2026-09-15";
    expect(confirmedKind(headline)).toBe("company press release");
    expect(confirmedKind(filing)).toBe("SEC filing");
    expect(confirmedKind("confirmed: Finnhub and Yahoo Finance agree")).toBe(CONFIRMED_KIND.calendars);
    expect(confirmedKind("confirmed: company announcement")).toBe(CONFIRMED_KIND.company);
    expect(confirmedKind("confirmed: something new the refresh starts writing 2026-09-01")).toBe(CONFIRMED_KIND.company);
    expect(confirmedKind(null)).toBe(CONFIRMED_KIND.company);

    const item: ReportingSoonItem = {
      ...base, symbol: "ACME", earnings_date: "2026-10-01", is_confirmed: true, source: "edgar",
      checked_at: TODAY_CHECK, confirmation: "confirmed", confirmation_note: headline, insight: null, vol_regime: null,
    };
    for (const note of [headline, filing]) {
      const s = reportingSoonSentence({ ...item, confirmation_note: note }, NOW);
      expect(s).not.toMatch(/2026|Announce|Item|Finnhub news|filed/);
    }
    expect(reportingSoonSentence(item, NOW)).toBe("Reports in 2 days (confirmed, company press release)");
    expect(reportingSoonSentence({ ...item, confirmation_note: filing }, NOW)).toBe("Reports in 2 days (confirmed, SEC filing)");
    expect(earningsClause("2026-10-21", "edgar", TODAY_CHECK, "confirmed", headline, NOW)).toBe("reports Oct 21 (confirmed, company press release)");
    // estimated dates keep the source and when it was checked
    expect(reportingSoonSentence({ ...item, confirmation: "estimated", source: "yfinance", is_confirmed: false }, NOW)).toBe(
      "Reports in 2 days (estimated, Yahoo Finance, checked today)");
  });

  it("a ticker with no confirmed date says so and when the calendar was checked", () => {
    expect(noDateClause(TODAY_CHECK, NOW)).toBe("No confirmed date yet (Finnhub, checked today)");
    expect(noDateClause(null, NOW)).toBe("No confirmed date yet (not yet checked)");
    const s: SuggestionItem = {
      ...base, symbol: "NODT", score: 3, reports_in_days: null, recent_move_pct: null, recent_move_5d: null,
      recent_outcome: null, event_date: null, insight: null, vol_regime: null,
      earnings_date: null, earnings_source: null, earnings_checked_at: TODAY_CHECK, earnings_confirmation: null, earnings_note: null,
    };
    expect(suggestionSentence(s, NOW)).toBe("No confirmed date yet (Finnhub, checked today)");
    expect(suggestionSentence({ ...s, insight: "Averages a ±8.2% earnings move, 2.1x the index median" }, NOW)).toBe(
      "Averages a ±8.2% earnings move, 2.1x the index median; no confirmed date yet (Finnhub, checked today)");
  });

  it("worth a look: the stored stat, then the next date at its level", () => {
    const s: SuggestionItem = {
      ...base, symbol: "WRTH", score: 5, reports_in_days: 8, recent_move_pct: null, recent_move_5d: null,
      recent_outcome: null, event_date: null, insight: "Beats estimates 90% of the time, versus 72% across the S&P", vol_regime: "iv_cheap",
      earnings_date: "2026-10-07", earnings_source: "finnhub", earnings_checked_at: TODAY_CHECK,
      earnings_confirmation: "estimated", earnings_note: null,
    };
    expect(suggestionSentence(s, NOW)).toBe(
      "Beats estimates 90% of the time, versus 72% across the S&P; reports around Oct 7 (estimated, Finnhub, checked today)");     // no IV cheap on worth a look
  });

  it("the tape: words only, the volatility tier, the options clause, then the report date at its level", () => {
    const u: UnusuallyActiveItem = {
      ...base, symbol: "VOLT", rv_rank: 99.4, rv_20d: 0.62, tier: "extreme", insight: null, vol_regime: null,
      iv_rv_spread_pp: -7.2, atm_iv: 0.548, iv_date: "2026-09-28",
      earnings_date: "2026-10-21", earnings_source: "edgar", earnings_checked_at: TODAY_CHECK,
      earnings_confirmation: "confirmed", earnings_note: "confirmed: 8-K Item 7.01 filed 2026-09-15",
    };
    expect(unusuallyActiveSentence(u, NOW)).toBe(
      "Its last month has been its choppiest in a year. Options are pricing a calmer month ahead. Reports Oct 21 (confirmed by the company).");
    expect(unusuallyActiveSentence({ ...u, rv_rank: TAPE_ONE_OF_CHOPPIEST_RANK, iv_rv_spread_pp: TAPE_OPTIONS_BAND_PP + 0.1 }, NOW)).toBe(
      "Its last month has been one of its choppiest in a year. Options are pricing an even bumpier month ahead. Reports Oct 21 (confirmed by the company).");
    expect(unusuallyActiveSentence({ ...u, rv_rank: TAPE_CHOPPIEST_RANK - 0.6, iv_rv_spread_pp: TAPE_OPTIONS_BAND_PP }, NOW)).toBe(
      "Its last month has been one of its choppiest in a year. Options are pricing about the same. Reports Oct 21 (confirmed by the company).");
    // no fresh chain: no options clause; an estimate says so; two calendars agreeing are not the company
    expect(unusuallyActiveSentence({ ...u, rv_rank: DISCOVER_ELEVATED_RV, iv_rv_spread_pp: null, iv_date: null, earnings_confirmation: "estimated", earnings_source: "finnhub" }, NOW)).toBe(
      "Its last month has been choppier than most of its past year. Reports around Oct 21 (estimated).");
    expect(unusuallyActiveSentence({ ...u, earnings_note: "confirmed: Finnhub and Yahoo Finance agree" }, NOW)).toContain("(confirmed by two calendars).");
    expect(unusuallyActiveSentence({ ...u, earnings_date: null }, NOW)).toBe(
      "Its last month has been its choppiest in a year. Options are pricing a calmer month ahead.");
    // the figures are the hover
    const receipt = tapeReceipt(u, NOW);
    expect(receipt).toContain("RV rank 99 of 100 against its own past year; 20-day realized volatility 62.0%");
    expect(receipt).toContain("Implied volatility 54.8% from the Sep 28 chain, 7.2 points below realized");
    expect(receipt).toContain("Reports Oct 21 (confirmed, SEC filing)");
  });

  it("one dominating session or a held rank replaces both clauses", () => {
    const note = "one session dominates the 20-day window: Oct 5, 2026 (+33.5%)";
    const u: UnusuallyActiveItem = {
      ...base, symbol: "PTC", rv_rank: 96.8, rv_20d: 1.07, tier: "extreme", insight: null, vol_regime: null, iv_rv_note: note,
      dominant_date: "2026-10-05", dominant_move_pct: 33.5, iv_rv_spread_pp: null,
      earnings_date: "2026-11-11", earnings_source: "finnhub", earnings_checked_at: TODAY_CHECK, earnings_confirmation: "estimated", earnings_note: null,
    };
    expect(unusuallyActiveSentence(u, NOW)).toBe("Its last month looks choppy mostly because of one big jump on Oct 5. Reports around Nov 11 (estimated).");
    expect(unusuallyActiveSentence({ ...u, dominant_move_pct: -26.5 }, NOW)).toContain("one big drop on Oct 5.");
    expect(tapeReceipt(u, NOW)).toContain("One session dominates the 20-day window: Oct 5, 2026 (+33.5%)");
    const held = { ...u, dominant_date: null, iv_rv_note: null, rank_hold_phrase: "Spun off Vylor on Oct 1", rank_hold_reason: "Spun off Vylor on Oct 1, 2026; 252 clean sessions after it are needed" };
    expect(unusuallyActiveSentence(held, NOW)).toBe("Spun off Vylor on Oct 1, so its past year doesn't compare yet. Reports around Nov 11 (estimated).");
    expect(tapeReceipt(held, NOW)).toContain("Rank held: Spun off Vylor on Oct 1, 2026");
    const s: SuggestionItem = {
      ...base, symbol: "PTC", score: 5, reports_in_days: 8, recent_move_pct: null, recent_move_5d: null, recent_outcome: null, event_date: null,
      insight: "Beats estimates 90% of the time, versus 72% across the S&P", vol_regime: null, iv_rv_note: note,
      earnings_date: null, earnings_source: null, earnings_checked_at: TODAY_CHECK, earnings_confirmation: null, earnings_note: null,
    } as SuggestionItem;
    expect(suggestionSentence(s, NOW)).not.toContain(note);                          // worth a look carries no options comparison at all
    expect(suggestionSentence({ ...s, vol_regime: "iv_rich" } as SuggestionItem, NOW)).not.toMatch(/\bIV\b/);
    expect(suggestionSentence({ ...s, vol_regime: "iv_cheap" } as SuggestionItem, NOW)).not.toMatch(/\bIV\b/);
  });

  it("no tape row carries a digit outside a date, or RV, IV, rank or pp", () => {
    const DATE = /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}\b/g;
    const rows: UnusuallyActiveItem[] = [];
    for (const rank of [100, 99, 98.6, 95, 94.4, 87, 85]) {
      for (const spread of [null, -12.3, -5, 0, 5.01, 22.7]) {
        for (const conf of ["confirmed", "estimated", "expected_unconfirmed", null]) {
          rows.push({
            ...base, symbol: "ROW", rv_rank: rank, rv_20d: 0.913, tier: "extreme", insight: "IV rich at +12pp vs realized · RV rank 92, extreme", vol_regime: "iv_rich",
            iv_rv_spread_pp: spread, atm_iv: spread == null ? null : 0.4, iv_date: spread == null ? null : "2026-10-07",
            earnings_date: conf ? "2026-10-28" : null, earnings_source: "finnhub", earnings_checked_at: TODAY_CHECK, earnings_confirmation: conf,
            earnings_note: conf === "confirmed" ? "confirmed: press release via Finnhub news 2026-09-02: Q3 2026 results on 10/28" : null,
          });
        }
      }
    }
    rows.push({ ...rows[0], dominant_date: "2026-09-29", dominant_move_pct: -26.52, iv_rv_note: "one session dominates the 20-day window: Sep 29, 2026 (-26.5%)" });
    rows.push({ ...rows[0], rank_hold_phrase: "Merged with AvalonBay on Aug 17", rank_hold_reason: "Merged with AvalonBay on Aug 17, 2026; 252 clean sessions after it are needed" });
    for (const r of rows) {
      const s = unusuallyActiveSentence(r, NOW);
      expect(s.replace(DATE, ""), s).not.toMatch(/\d/);
      expect(s, s).not.toMatch(/\b(RV|IV|rank|pp)\b|%/i);
    }
  });

  it("the tape's subtitle says it in words and links volatile to the glossary", () => {
    const page = read("app/discover/page.tsx");
    expect(page).toContain('Stocks more <ExplainTip term="realized volatility">volatile</ExplainTip> than usual, each compared with its own past year.');
    expect(page).not.toContain("Volatility high vs. their own norm");
    expect(page).toContain("title={tapeReceipt(item)}");
  });

  it("just reported: the outcome, then the move against its typical one", () => {
    const j: JustReportedItem = {
      ...base, symbol: "RPTD", event_date: "2026-09-25", pct_change_1d: -6.3, outcome: "beat",
      insight: "Moved -6.3% on the 1-day reaction; its typical beat moves +2.7%", vol_regime: null,
    };
    expect(justReportedSentence(j)).toBe("Beat estimates; moved -6.3% on the 1-day reaction; its typical beat moves +2.7%");
    expect(justReportedSentence({ ...j, outcome: "miss", insight: null, pct_change_1d: 4.25 })).toBe(
      "Missed estimates; moved +4.3% on the 1-day reaction");
    expect(justReportedSentence({ ...j, outcome: "unknown", insight: null, pct_change_1d: null })).toBe(
      "Reported; beat or miss not recorded");
  });

  it("every outcome the API sends has words", () => {
    const outcomes: EarningsOutcome[] = ["beat", "miss", "meet", "unknown"];
    for (const o of outcomes) expect(OUTCOME_LEAD[o]).toBeTruthy();
    expect(Object.keys(OUTCOME_LEAD).sort()).toEqual([...outcomes].sort());
  });

  it("from the ledger: direction, strategy, entry, now, and status", () => {
    const p: LatestPickItem = {
      id: "p1", symbol: "IVY", picked_direction: "bullish", strategy: "Long call", entry_price: 182.1,
      current_price: 190, unrealized_move_pct: 4.34, status: "open", generated_at: "2026-09-20T12:00:00Z",
      expiration: "2026-10-16", direction_hit: null, option_pnl_pct: null,
    } as LatestPickItem;
    expect(latestPickSentence(p)).toBe("Bullish pick (Long call), entered at $182.10, now $190.00 (stock +4.3%); open");
    expect(latestPickSentence({ ...p, picked_direction: "bearish", strategy: null, current_price: null, unrealized_move_pct: null, status: "closed", option_pnl_pct: 35 })).toBe(
      "Bearish pick, entered at $182.10; closed, option P&L +35%");
  });

  it("no sentence ends in an ellipsis", () => {
    const all = [
      earningsClause("2026-10-07", "finnhub", TODAY_CHECK, "estimated", null, NOW),
      earningsClause(null, null, null, null, null, NOW),
    ];
    for (const s of all) expect(s).not.toMatch(/(…|\.\.\.)$/);
  });
});
