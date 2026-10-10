import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { IvyBacktest, IvyRule } from "@/lib/ivyRule";
import { evidenceSummary, limitLines, refusalTile, ruleTiles } from "@/lib/ivyRule";
import { IVY_BACKTEST_ENCODING, backtestScale, ivyBacktestLegend } from "@/lib/encodings/ivyBacktest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

const RULE: IvyRule = {
  momentum_cutoff_pct: -10, momentum_lookback_days: 20, min_prior_quarters: 8, implied_move_multiple: 1.2,
  exit_trading_days: 5, candidate_window_days: 7, max_new_picks_per_night: 3, max_open_picks: 10,
  ledger_start: "2026-09-15", ledger_public: false, chain_fresh_trading_days: 2,
};
const BACKTEST: IvyBacktest = {
  as_of_date: "2026-09-11", run_at: "2026-09-21T22:40:18+00:00", passed: true,
  folds: [
    { label: "2023", setups: 47, hits: 28, hit_rate: 0.595745, base_n: 1960, base_rate: 0.515306 },
    { label: "2024", setups: 70, hits: 38, hit_rate: 0.542857, base_n: 1977, base_rate: 0.535660 },
    { label: "2025-26", setups: 248, hits: 132, hit_rate: 0.532258, base_n: 3481, base_rate: 0.521689 },
  ],
  setups: 365, hits: 198, hit_rate: 0.542466, base_n: 7418, base_rate: 0.523726,
};

describe("Meet Ivy: tiles, evidence and limits come from the rule", () => {
  it("fills every tile from the rule and follows it when it changes", () => {
    expect(ruleTiles(RULE).map((t) => t.figure)).toEqual(["7", "−10%", "8"]);
    expect(ruleTiles(RULE)[1].caption).toBe("Down more than 10% over the prior 20 trading days");
    expect(refusalTile(RULE).caption).toBe("If the implied move is more than 1.2 times the stock's usual earnings move, she refuses.");
    const moved = { ...RULE, momentum_cutoff_pct: -15, min_prior_quarters: 12, implied_move_multiple: 1.5, candidate_window_days: 5 };
    expect(ruleTiles(moved).map((t) => t.figure)).toEqual(["5", "−15%", "12"]);
    expect(refusalTile(moved).figure).toBe("1.5×");
  });
  it("the evidence keeps the approved numbers and the honest sentence", () => {
    const e = evidenceSummary(RULE, BACKTEST)!;
    expect([e.setups, e.hitRate, e.baseRate, e.years]).toEqual([365, "54.2", "52.4", "2023, 2024, and 2025-26"]);
    expect(e.honest).toBe("That edge is small, and most of it came in 2023 (59.6% against 51.5%). Since then it has been about a point. " +
      "Those years chose the rule as much as tested it, so the only test that counts is the live record, kept on schedule since September 15, 2026 and public at launch. " +
      "A small edge you will be able to check beats a large one you can't.");
    expect(evidenceSummary(RULE, null)).toBeNull();
  });
  it("the limits use the rule's caps and the ledger flag", () => {
    const lines = limitLines(RULE);
    expect(lines[0]).toBe("At most 3 new picks a night");
    expect(lines[1]).toBe("At most 10 open at once");
    expect(lines).toContain("Every pick since September 15, 2026 is recorded the night it is made. The ledger goes public at launch.");
    expect(lines).toContain("No bearish calls. The data has not earned them yet.");
    expect(limitLines({ ...RULE, ledger_public: true })).toContain("Every pick since September 15, 2026 is on the ledger, losses next to wins.");
  });
  it("the evidence chart reads one encoding, and its legend names every mark", () => {
    expect(ivyBacktestLegend().map((l) => l.label)).toEqual(Object.values(IVY_BACKTEST_ENCODING).map((e) => e.label));
    const looks = Object.values(IVY_BACKTEST_ENCODING).map((e) => `${e.color}|${e.filled}`);
    expect(new Set(looks).size).toBe(looks.length);
    expect(backtestScale([0.515, 0.596])).toEqual({ min: 50, max: 61 });
    const page = read("app/ivy/page.tsx");
    expect(page).toContain("ivyBacktestLegend()");
    expect(page).not.toMatch(/54\.2|52\.4|59\.6|51\.5|\b365\b/);
  });
});
