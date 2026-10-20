// The ticker page's header change, report cards, options verdict and range band each match the API values they are built from,
// and the verdict never states a comparison the stored numbers do not support. Fixtures are trimmed copies of production
// answers from 2026-10-13 (TSLA quote and 7d chart, NVDA and VMRK reactions, NVDA options read).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { HistoricalReaction, TickerChart, TickerQuote } from "@/lib/api";
import { fmtChange, hasBars, openingPeriod, periodChange, quoteTimeLine, sessionOn, DIRECTION_STYLE } from "@/lib/priceHeader";
import type { MarketSession, MarketSessionDay } from "@/lib/api";
import { averageMoveLine, epsLine, fmtMove, reportCards, typicalMove, storedTypical, whyItMoved } from "@/lib/reportCards";
import { compareMoves, MOVE_LESS_RATIO, MOVE_MIN_REPORTS, MOVE_MORE_RATIO, optionsVerdict, type ReportMoveFacts, type VerdictInput } from "@/lib/optionsVerdict";
import { comparisonParts } from "@/lib/moveComparison";
import { BACK_TO_CHART, EVIDENCE_VIEWS } from "@/lib/evidenceViews";
import { EARNINGS_MARKER_ENCODING, earningsMarkerLegend } from "@/lib/encodings/earningsMarkers";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { OptionsVerdictView } from "@/components/ticker/OptionsVerdict";
import { VERDICT_SENTENCE_SHOWN } from "@/lib/optionsVerdict";

const TSLA_QUOTE = { symbol: "TSLA", price: 375.23, change: -2.8, change_pct: -0.7407, high: 377.05, low: 371.3, open: 372.325, prev_close: 378.03,
  timestamp: 1791921600, quote_basis: "last_trade", delay_minutes: null, sparkline: [], quote_state: "ok" } as unknown as TickerQuote;
const TSLA_7D = { symbol: "TSLA", period: "7d", start_price: 376.31, history_state: "ok", earnings_markers: [],
  history: [{ date: "2026-10-05T09:30:00.000-04:00", close: 376.31 }, { date: "2026-10-12T15:30:00.000-04:00", close: 378.08 }] } as unknown as TickerChart;

const row = (o: Partial<HistoricalReaction>): HistoricalReaction => ({
  id: o.event_date ?? "x", ticker_id: "t", event_id: null, event_type: "earnings", event_date: "2026-01-01", close_before: null, open_after: null, close_after: null,
  pct_change_1d: null, pct_change_3d: null, pct_change_5d: null, volume_before: null, volume_after: null, notes: null, eps_estimate: null, eps_actual: null,
  revenue_estimate: null, revenue_actual: null, outcome: "unknown", created_at: "", eps_surprise_pct: null, report_timing: null, ...o,
} as HistoricalReaction);

const NVDA_ROWS = [
  row({ event_date: "2026-05-20", report_timing: "amc", outcome: "beat", eps_actual: "1.8700", eps_estimate: "1.7700", eps_surprise_pct: 5.6, eps_surprise_display_pct: 5.6, eps_surprise_dollars: 0.1, pct_change_1d: "-1.7720", pct_change_3d: "-3.8529", pct_change_5d: "-4.1258" }),
  row({ event_date: "2026-08-26", report_timing: "amc", outcome: "beat", eps_actual: "2.2200", eps_estimate: "2.0900", eps_surprise_pct: 6.2, eps_surprise_display_pct: 6.2, eps_surprise_dollars: 0.13, pct_change_1d: "8.7380", pct_change_3d: "5.3038", pct_change_5d: "7.0352" }),
];
const VMRK_ROW = row({ event_date: "2026-07-22", report_timing: "amc", outcome: "no_reported_figure", eps_estimate: "0.3600", pct_change_1d: "-0.0146", pct_change_3d: "-1.5376", pct_change_5d: "0.8200" });
const NVDA_SUMMARY = { avg_abs_1d: 6.46, total_quarters: 21, last_event_date: "2026-08-26" };

// 2026-10-13 is a Tuesday; New York is UTC-4.
const NY = (hhmm: string, day = "2026-10-13") => Date.parse(`${day}T${hhmm}:00-04:00`);

describe("header change matches the API values it comes from", () => {
  it("1D is the quote's own change and percent against the previous close", () => {
    const c = periodChange("1d", TSLA_QUOTE, null)!;
    expect(c.change).toBe(TSLA_QUOTE.change);
    expect(c.pct).toBe(TSLA_QUOTE.change_pct);
    expect(c.since).toBe("since the previous close");
    expect(fmtChange(c)).toBe("-2.80 (-0.74%)");
    expect(c.direction).toBe("down");
  });
  it("other periods are the quote's price against the chart's start_price, dated by the first bar", () => {
    const c = periodChange("7d", TSLA_QUOTE, TSLA_7D)!;
    expect(c.change).toBeCloseTo(375.23 - 376.31, 10);
    expect(c.pct).toBeCloseTo(((375.23 - 376.31) / 376.31) * 100, 10);
    expect(c.since).toBe("since Oct 5, 2026");
    expect(fmtChange(c)).toBe("-1.08 (-0.29%)");
  });
  it("no change without both sides, and the color follows the sign as printed", () => {
    expect(periodChange("7d", TSLA_QUOTE, { ...TSLA_7D, start_price: null })).toBeNull();
    expect(periodChange("1d", { ...TSLA_QUOTE, change: null }, null)).toBeNull();
    expect(periodChange("1d", { ...TSLA_QUOTE, change: 0.004, change_pct: 0.001 }, null)!.direction).toBe("flat");
    expect(DIRECTION_STYLE.up.stroke).not.toBe(DIRECTION_STYLE.down.stroke);
  });
  it("opens on 1D when it has bars, else the shortest period that does", async () => {
    const empty = { history: [], history_state: "no_data" } as unknown as TickerChart;
    const got = await openingPeriod(async (p) => (p === "1d" ? empty : { ...TSLA_7D, period: p }));
    expect(got?.period).toBe("7d");
    expect(got?.skipped).toEqual(["1d"]);
    expect(hasBars(empty)).toBe(false);
    expect((await openingPeriod(async (p) => ({ ...TSLA_7D, period: p })))?.period).toBe("1d");
  });
});

// Sessions as backend services/market_status serves them (backend tests/test_market_status.py pins the calendar itself)
const day = (date: string, close: string | null, reason: MarketSessionDay["reason"] = "regular", off = "-04:00"): MarketSessionDay => ({
  date, is_trading_day: close != null, half_day: reason === "half_day", reason,
  open_at: close ? `${date}T09:30:00${off}` : null, close_at: close ? `${date}T${close}:00${off}` : null });
const SESSION = (today: MarketSessionDay, next: MarketSessionDay | null = null): MarketSession => ({ as_of: "", is_open: false, today, next });
const OCT13 = SESSION(day("2026-10-13", "16:00"), day("2026-10-14", "16:00"));
const OCT14 = SESSION(day("2026-10-14", "16:00"), day("2026-10-15", "16:00"));
const OCT17 = SESSION(day("2026-10-17", null, "weekend"), day("2026-10-19", "16:00"));

describe("the quote's time line follows the exchange calendar at every hour", () => {
  const delayed = { timestamp: Math.floor(NY("13:02") / 1000), quote_basis: "delayed" as const, delay_minutes: 15 };
  it("in session with a delayed quote from today it states the delay and the time", () => {
    expect(quoteTimeLine(delayed, NY("13:20"), OCT13)).toEqual({ state: "delayed_session", text: "Delayed 15 minutes. Last trade at 1:02 PM ET on Oct 13, 2026." });
  });
  it("after the close, overnight and on a weekend it says the market is closed and names the close it shows", () => {
    expect(quoteTimeLine(TSLA_QUOTE, NY("20:11"), OCT13)?.text).toBe("Market closed. Showing the last trade at 4:00 PM ET on Oct 13, 2026.");
    const close = { ...TSLA_QUOTE, quote_basis: "close" as const };
    expect(quoteTimeLine(close, NY("08:00", "2026-10-14"), OCT14)?.text).toBe("Market closed. Showing the close at 4:00 PM ET on Oct 13, 2026.");
    expect(quoteTimeLine(close, NY("12:00", "2026-10-17"), OCT17)?.state).toBe("closed");   // a Saturday
  });
  it("a holiday is closed all day and a half day closes at 1 PM", () => {
    const close = { ...TSLA_QUOTE, quote_basis: "close" as const };
    const thanksgiving = SESSION(day("2026-11-26", null, "holiday", "-05:00"), day("2026-11-27", "13:00", "half_day", "-05:00"));
    expect(quoteTimeLine(close, NY("11:00", "2026-11-26").valueOf() + 3_600_000, thanksgiving)?.state).toBe("closed");
    const half = SESSION(day("2026-11-27", "13:00", "half_day", "-05:00"));
    const at = (hhmm: string) => Date.parse(`2026-11-27T${hhmm}:00-05:00`);
    const live = (ms: number) => ({ ...delayed, timestamp: Math.floor(ms / 1000) - 900 });
    expect(quoteTimeLine(live(at("12:59")), at("12:59"), half)?.state).toBe("delayed_session");
    expect(quoteTimeLine(live(at("13:30")), at("13:30"), half)?.state).toBe("closed");
  });
  it("in session without a delayed quote from today, or with no session answer for today, it makes no claim about the market", () => {
    const yesterday = { ...TSLA_QUOTE, quote_basis: "close" as const, timestamp: Math.floor(NY("16:00", "2026-10-12") / 1000) };
    const line = quoteTimeLine(yesterday, NY("11:00"), OCT13)!;
    expect(line.state).toBe("session_no_live");
    expect(line.text).not.toMatch(/closed|open|live|now|today/i);
    expect(quoteTimeLine({ ...delayed, timestamp: Math.floor(NY("15:59", "2026-10-12") / 1000) }, NY("11:00"), OCT13)!.text).not.toMatch(/Delayed/);
    for (const s of [null, SESSION(day("2026-10-09", "16:00"))]) {
      expect(quoteTimeLine(TSLA_QUOTE, NY("20:11"), s)!.state).toBe("session_no_live");
      expect(quoteTimeLine(delayed, NY("13:20"), s)!.text).not.toMatch(/closed|Delayed/);
    }
    expect(sessionOn(OCT13, NY("08:00", "2026-10-14"))?.date).toBe("2026-10-14");      // read the day before: the next session covers today
  });
  it("never says closed inside the session window, never says delayed outside it", () => {
    for (let m = 0; m < 24 * 60; m += 15) {
      const hh = String(Math.floor(m / 60)).padStart(2, "0"), mm = String(m % 60).padStart(2, "0");
      const inSession = m >= 9 * 60 + 30 && m < 16 * 60;
      const now = NY(`${hh}:${mm}`);
      expect(/Market closed/.test(quoteTimeLine(TSLA_QUOTE, now, OCT13)!.text)).toBe(!inSession);
      expect(/Delayed/.test(quoteTimeLine({ ...delayed, timestamp: Math.floor(now / 1000) - 900 }, now, OCT13)!.text)).toBe(inSession);
    }
  });
});

describe("report cards match the stored rows", () => {
  it("newest first, each figure the API's value, the EPS line against a year earlier", () => {
    const cards = reportCards(NVDA_ROWS.map((r, i) => ({ ...r, eps_line: i ? "EPS $2.22, up 111.4% from $1.05 a year ago" : null })));
    expect(cards.map((c) => c.eventDate)).toEqual(["2026-08-26", "2026-05-20"]);
    const c = cards[0];
    expect(c.date).toBe("Aug 26, 2026");
    expect(c.timing).toBe("After the close");
    expect(c.eps).toBe("EPS $2.22, up 111.4% from $1.05 a year ago");
    expect(c.moves.map((m) => m.value)).toEqual([8.738, 5.3038, 7.0352]);
    expect(c.moves.map((m) => fmtMove(m.value!))).toEqual(["+8.7%", "+5.3%", "+7.0%"]);
  });
  it("no card shows an estimate, a beat, a miss or a surprise, even from a row that carries them", () => {
    for (const r of [...NVDA_ROWS, VMRK_ROW]) {
      const c = reportCards([r])[0];
      expect(`${c.eps ?? ""} ${c.epsAbsent ?? ""} ${whyItMoved(r, typicalMove(NVDA_SUMMARY))?.text ?? ""}`).not.toMatch(/\b(beat|miss|missed|met|estimate|surprise)/i);
    }
  });
  it("a report without an EPS line shows the absence", () => {
    const c = reportCards([VMRK_ROW])[0];
    expect(c.eps).toBeNull();
    expect(c.epsAbsent).toBe("No EPS figure from SEC filings for this report.");
    expect(epsLine(row({ eps_line: "EPS $0.31, down 3.0% from $0.32 a year ago" })).eps).toBe("EPS $0.31, down 3.0% from $0.32 a year ago");
  });
  it("the tapped line is the move, from stored facts only, and leaves missing parts out", () => {
    const typical = typicalMove(NVDA_SUMMARY)!;
    const w = whyItMoved(NVDA_ROWS[1], typical)!;
    expect(w.text).toBe("The stock rose 8.7% over the first trading day after the report, more than its typical 6.5% move.");
    expect(w.comparison).toBe(compareMoves(8.7, 6.5));
    expect(w.receipt).toBe("Typical move is the average size of the first-day move across 21 reports through Aug 26, 2026.");
    expect(whyItMoved(VMRK_ROW, null)!.text).toBe("The stock was unchanged over the first trading day after the report.");
    expect(whyItMoved(row({ outcome: "miss", eps_actual: "1", eps_estimate: "1.2", eps_surprise_pct: -16.7 }), typical)).toBeNull();
  });
  it("W7: the average move after past reports is the signed mean, with its sign", () => {
    expect(averageMoveLine(1.2)).toBe("After past reports, the stock moved +1.2% the next day on average.");
    expect(averageMoveLine(-0.04)).toBe("After past reports, the stock moved 0.0% the next day on average.");
    expect(averageMoveLine(null)).toBeNull();
  });
  it("a typical move needs the minimum sample before any card compares with it", () => {
    expect(typicalMove({ ...NVDA_SUMMARY, total_quarters: MOVE_MIN_REPORTS - 1 })).toBeNull();
    expect(storedTypical({ ...NVDA_SUMMARY, total_quarters: 3 })?.reports).toBe(3);
    expect(storedTypical({ ...NVDA_SUMMARY, exclusion_reason: "excluded" })).toBeNull();
    expect(whyItMoved(NVDA_ROWS[1], null)!.comparison).toBeNull();
  });
});

const NVDA_SENTENCE = "Options price a move of about 6.9% from the report itself, about the same as the 6.5% it has moved on a typical report (options from Oct 12, 2026).";
const NVDA_REPORT: ReportMoveFacts = {
  state: "ok", comparison: NVDA_SENTENCE, moveComparison: "about its usual", typicalPct: 6.5, typicalN: 21, heldFacts: [],
  move: { state: "ok", pct: 0.0690, e: 0.08625, t2_years: 39 / 365, report_date: "2026-11-17", version: 1,
          before: { expiration: "2026-11-13", chain_date: "2026-10-12", atm_strike: 227.5, atm_iv: 0.431 },
          after: { expiration: "2026-11-20", chain_date: "2026-10-12", atm_strike: 227.5, atm_iv: 0.512 } },
};
const NVDA_VERDICT: VerdictInput = {
  symbol: "NVDA",
  facts: { expected_move_pct: 0.09278897136797455, implied_range_low: 205.32, implied_range_high: 247.32, expiration_used: "2026-11-20",
    next_earnings_date: "2026-11-17", chain_date: "2026-10-12", current_price: 226.32, price_as_of: "2026-10-12T20:00:00+00:00" },
  nextReport: "2026-11-17", confirmation: "confirmed",
  report: NVDA_REPORT,
  typical: { pct: 6.46, reports: 21, through: "2026-08-26" },
  quote: { price: 228.52, asOf: "last trade on Oct 13, 2026" },
};

describe("the options verdict states the API's report move and never overstates", () => {
  it("says the API's sentence, with both expirations and their IVs as the receipt, and the range band", () => {
    const v = optionsVerdict(NVDA_VERDICT);
    if (v.kind !== "verdict") throw new Error("expected a verdict");
    expect(v.sentence).toBe(NVDA_SENTENCE);
    expect(v.comparison).toBe("about its usual");
    expect(v.reportPct).toBe(6.9);
    expect(v.receipt).toBe("From the Oct 12, 2026 options data, the Nov 13, 2026 expiration at 43.1% and the Nov 20, 2026 expiration at 51.2% implied volatility, for the report on Nov 17, 2026. Typical move is the average size of the first-day move across 21 reports through Aug 26, 2026.");
    expect(v.band!.low).toBe(205.32);
    expect(v.band!.high).toBe(247.32);
    expect(v.band!.marker).toBe(228.52);
    expect(v.band!.lowPos).toBeLessThan(v.band!.markerPos);
    expect(v.band!.markerPos).toBeLessThan(v.band!.highPos);
  });
  it("the ticker verdict and Discover's line are the same sentence with the same figures", () => {
    const v = optionsVerdict(NVDA_VERDICT);
    const discover = { comparison: NVDA_SENTENCE, report_move_pct: 6.9, typical_move_pct: 6.5 };     // the reporting-soon item the API sends for NVDA
    const parts = comparisonParts(discover)!;
    expect(v.kind === "verdict" && v.sentence).toBe(parts.map((p) => p.text).join(""));
    expect(v.kind === "verdict" && [v.reportPct, v.typicalPct]).toEqual([discover.report_move_pct, discover.typical_move_pct]);
  });
  it("a term-method move names the first two expirations after the report in its receipt", () => {
    const v = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, move: { ...NVDA_REPORT.move!, method: "term", before: null,
      later: { expiration: "2026-12-18", chain_date: "2026-10-12", atm_strike: 227.5, atm_iv: 0.45 }, t3_years: 67 / 365 } } });
    expect(v.kind === "verdict" && v.receipt).toBe("From the Oct 12, 2026 options data, the Nov 20, 2026 expiration at 51.2% and the Dec 18, 2026 expiration at 45.0% implied volatility, the first two after the report on Nov 17, 2026. Typical move is the average size of the first-day move across 21 reports through Aug 26, 2026.");
  });
  it("a floored term-method base names the 20-day realized volatility in the receipt", () => {
    const v = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, move: { ...NVDA_REPORT.move!, method: "term", before: null,
      later: { expiration: "2026-12-18", chain_date: "2026-10-12", atm_strike: 227.5, atm_iv: 0.45 }, t3_years: 67 / 365,
      base_floored: true, rv_20d: 0.312, raw_base_variance: 0.01, base_variance: 0.312 ** 2 } } });
    expect(v.kind === "verdict" && v.receipt).toContain("the first two after the report on Nov 17, 2026. The stock's usual swing is taken as its 20-day realized volatility of 31.2%, higher than the expirations imply.");
    const raw = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, move: { ...NVDA_REPORT.move!, method: "term", before: null,
      later: { expiration: "2026-12-18", chain_date: "2026-10-12", atm_strike: 227.5, atm_iv: 0.45 }, t3_years: 67 / 365, base_floored: false, rv_20d: 0.1 } } });
    expect(raw.kind === "verdict" && raw.receipt).not.toMatch(/realized/);
  });
  it("an unsteady term move states the sentence and shows no figure", () => {
    const text = "The options don't give a steady read of the report move yet.";
    const v = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, state: "unsteady", comparison: text, moveComparison: null,
      move: { ...NVDA_REPORT.move!, method: "term", before: null,
        later: { expiration: "2026-12-18", chain_date: "2026-10-12", atm_strike: 227.5, atm_iv: 0.45 }, t3_years: 67 / 365 } } });
    expect(v.kind === "verdict" && [v.sentence, v.comparison, v.reportPct, v.typicalPct]).toEqual([text, null, null, null]);
  });
  it("says plainly when the options don't separate a report move, with no comparison", () => {
    const text = "The options don't separate a report move from the stock's usual swing.";
    const v = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, state: "not_separated", comparison: text, moveComparison: null,
      move: { ...NVDA_REPORT.move!, state: "not_separated", pct: null, e: null } } });
    expect(v.kind === "verdict" && [v.sentence, v.comparison, v.reportPct]).toEqual([text, null, null]);
    const none = optionsVerdict({ ...NVDA_VERDICT, report: { state: "no_legs", comparison: "Too few expirations near the report are on hand to separate a report move.", move: null, heldFacts: [] } });
    expect(none.kind === "verdict" && none.sentence).toMatch(/^Too few expirations/);
    expect(none.kind === "verdict" && none.receipt).toBe("From the Oct 12, 2026 options data, for the report on Nov 17, 2026.");
  });
  it("no comparison words without a typical move over enough reports, and a held fact drops the verdict", () => {
    const thin = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, moveComparison: null, typicalN: MOVE_MIN_REPORTS - 1,
      comparison: "Options price a move of about 6.9% from the report itself (options from Oct 12, 2026)." } });
    expect(thin.kind === "verdict" && thin.sentence).not.toMatch(/typical|more|less|same/);
    expect(thin.kind === "verdict" && thin.why).toMatch(/fewer than the 8/);
    const heldTypical = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, moveComparison: null, typicalPct: null, heldFacts: ["typical_move"],
      comparison: "Options price a move of about 6.9% from the report itself (options from Oct 12, 2026)." } });
    expect(heldTypical.kind === "verdict" && heldTypical.why).toBe("The typical move is on hold while we verify it, so the move is not compared with one.");
    const heldImplied = optionsVerdict({ ...NVDA_VERDICT, report: { ...NVDA_REPORT, heldFacts: ["implied_move"] } });
    expect(heldImplied.kind).toBe("absent");
    expect(storedTypical({ ...NVDA_SUMMARY, held: true })).toBeNull();      // the cards compare with nothing while it is held
  });
  it("gives way to one plain line without a report date or a confirmed date; an older API shows the range alone", () => {
    const line = (o: Partial<VerdictInput>) => { const v = optionsVerdict({ ...NVDA_VERDICT, ...o }); return v.kind === "absent" ? v.line : null; };
    expect(line({ nextReport: null })).toBe("No upcoming report date is on file for NVDA, so there is no options verdict.");
    expect(line({ confirmation: "estimated" })).toBe("NVDA hasn't confirmed its next report date, so there's no options verdict yet.");
    const old = optionsVerdict({ ...NVDA_VERDICT, report: null });
    expect(old.kind === "verdict" && [old.sentence, old.band?.high]).toEqual([null, 247.32]);
    expect(line({ report: null, facts: { ...NVDA_VERDICT.facts, expected_move_pct: null } })).toBe("No usable options prices are on file for NVDA, so there is no options verdict.");
    expect(line({ report: null, nextReport: "2026-11-18" })).toBe("The options data on file was priced for a different report date, so there is no options verdict.");
  });
  it("without a quote the band marks the price the range was computed from, with its date", () => {
    const v = optionsVerdict({ ...NVDA_VERDICT, quote: null });
    expect(v.kind === "verdict" && v.band?.marker).toBe(226.32);
    expect(v.kind === "verdict" && v.band?.markerLabel).toBe("price on Oct 12, 2026");
  });
});

describe("mirrors and legends", () => {
  it("the comparison constants match backend services/move_comparison", () => {
    const py = readFileSync(join(__dirname, "../../../../backend/app/services/move_comparison.py"), "utf8");
    const val = (name: string) => Number(py.match(new RegExp(`^${name} = ([\\d.]+)`, "m"))![1]);
    expect(MOVE_MORE_RATIO).toBe(val("MORE_RATIO"));
    expect(MOVE_LESS_RATIO).toBe(val("LESS_RATIO"));
    expect(MOVE_MIN_REPORTS).toBe(val("MIN_REPORTS"));
  });
  it("the phrases Discover links are the ones the backend sentence says", () => {
    const py = readFileSync(join(__dirname, "../../../../backend/app/services/move_comparison.py"), "utf8");
    expect(py).toContain('Options price a move of about {report_pct:.1f}% from the report itself');
    expect(py).toContain('the "\n            f"{typical_pct:.1f}% it has moved on a typical report');
  });
  it("the price chart legend names each entry once", () => {
    for (const item of earningsMarkerLegend()) {
      const labels = item.label.split(" / ");
      expect(new Set(labels).size, item.label).toBe(labels.length);
    }
  });
});

describe("preview state (2026-10-14): the report-move verdict, price uncolored, met has its own marker", () => {
  it("the Options opening shows the API's sentence, its receipt and the range by the expiration", () => {
    expect(VERDICT_SENTENCE_SHOWN).toBe(true);
    const html = renderToStaticMarkup(createElement(OptionsVerdictView, { verdict: optionsVerdict(NVDA_VERDICT) }));
    for (const want of ["$205.32", "$247.32", "$228.52", "Nov 20, 2026", "from the report itself", "From the Oct 12, 2026 options data, for the report on Nov 17, 2026."]) expect(html).toContain(want);
    const older = renderToStaticMarkup(createElement(OptionsVerdictView, { verdict: optionsVerdict({ ...NVDA_VERDICT, report: null }) }));
    expect(older).toContain("$247.32");
    expect(older).not.toMatch(/typical|more than|less than|same as|from the report itself/);
  });
  it("only the change and the chart line take the direction color", () => {
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    expect(page).toContain('"text-4xl font-bold tabular-nums tracking-tight text-foreground" data-testid="header-price"');
    expect(page).toContain("data-testid=\"header-change\"");
  });
  it("every report is the one neutral Earnings date mark, so a settling report is never labelled no EPS data", () => {
    expect(Object.values(EARNINGS_MARKER_ENCODING).map((v) => v.label)).toEqual(["Earnings date"]);
    expect(earningsMarkerLegend().map((l) => l.label)).toEqual(["Earnings date"]);
  });
});

describe("the Evidence switch", () => {
  it("has two views, Chart first and the default, and no fold left behind", () => {
    expect(EVIDENCE_VIEWS.map((v) => v.label)).toEqual(["Chart", "Reports"]);
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    expect(page).toContain("useState<EvidenceView>(EVIDENCE_VIEWS[0].key)");
    expect(page).not.toContain("Distribution and peer comparison");
    expect(page).toContain('data-testid="evidence-switch"');
  });
  it("a report picked on the chart opens Reports at its card, and Reports then offers the way back", () => {
    const page = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    expect(page).toContain("<ReactionChart reactions={reactions} onPick={(date) => {");
    expect(page).toMatch(/setEvidenceView\("reports"\);\s*setPickedReport/);
    expect(page).toContain("picked={pickedReport}");
    expect(BACK_TO_CHART).toBe("Back to the chart");
    const cards = readFileSync(join(__dirname, "../../components/ticker/ReportCards.tsx"), "utf8");
    expect(cards).toContain("const showAll = all || pickedAt >= FIRST_SHOWN;");        // a picked report past the first eight shows them all
    expect(cards).toContain('scrollIntoView({ block: "center"');
    expect(cards).toContain("clickClearsPick(e, lit)");
    expect(cards).not.toContain("setTimeout");                                    // no timed fade
    expect(cards).toContain("{BACK_TO_CHART}");
  });
});
