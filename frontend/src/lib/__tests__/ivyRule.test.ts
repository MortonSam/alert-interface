import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import {
  type IvyBacktest, type IvyRule,
  chainFreshnessSentence, exitRuleSentence, ledgerRecordSentence, noForcedCallsSentence,
  oneRuleParagraph, restOfRecordPhrase, scoreKeepingPhrase, whoSheIsLine,
} from "../ivyRule";

const SRC = join(__dirname, "../..");

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

describe("the One rule paragraph", () => {
  it("fills every slot from the rule and the stored backtest, keeping the approved wording", () => {
    expect(oneRuleParagraph(RULE, BACKTEST)).toBe(
      "Ivy looks for one setup. A company reports earnings in the next few days, its stock has fallen more than 10% over the prior 20 trading days, and it has at least 8 quarters of earnings history. " +
      "That rule was tested against 2023, 2024, and 2025-26. Across 365 setups the stock was higher five days later 54.2% of the time, against 52.4% for all earnings reports in those years. " +
      "That edge is small, and most of it came in 2023 (59.6% against 51.5%). Since then it has been about a point. " +
      "Those years chose the rule as much as tested it, so the only test that counts is the live record, kept since September 15, 2026. A small edge you can check beats a large one you can't. " +
      "Before she buys anything, Ivy checks what the options market is pricing. If the implied move is more than 1.2 times the stock's usual earnings move, she refuses. " +
      "Every pick carries its receipt, with the number of comparable setups, the base rate, the expected move, and what the options were pricing. She makes no bearish calls. The data has not earned them yet.",
    );
  });

  it("follows the numbers when they change", () => {
    const rule = { ...RULE, momentum_cutoff_pct: -15, min_prior_quarters: 12, implied_move_multiple: 1.5, ledger_start: "2027-01-04" };
    const text = oneRuleParagraph(rule, BACKTEST);
    expect(text).toContain("more than 15%");
    expect(text).toContain("at least 12 quarters");
    expect(text).toContain("more than 1.5 times");
    expect(text).toContain("kept since January 4, 2027");
  });

  it("'about a point' is computed, not assumed", () => {
    expect(restOfRecordPhrase(BACKTEST, 0)).toBe("Since then it has been about a point.");
    const strong = { ...BACKTEST, folds: BACKTEST.folds.map((f, i) => (i === 0 ? f : { ...f, hits: Math.round(f.setups * 0.6), hit_rate: 0.6 })) };
    expect(restOfRecordPhrase(strong, 0)).toMatch(/about \d+ points\.$/);
    const flat = { ...BACKTEST, folds: BACKTEST.folds.map((f, i) => (i === 0 ? f : { ...f, hits: Math.round(f.setups * (f.base_rate ?? 0)), hit_rate: f.base_rate })) };
    expect(restOfRecordPhrase(flat, 0)).toBe("Since then it has been close to zero.");
    expect(restOfRecordPhrase(BACKTEST, 2)).toMatch(/^In the other years/);
  });

  it("says nothing about a backtest when none is stored", () => {
    const text = oneRuleParagraph(RULE, null);
    expect(text).not.toContain("tested against");
    expect(text).toContain("kept since September 15, 2026");
  });
});

describe("claims that depend on flags and constants", () => {
  it("'in public' only when the ledger is public", () => {
    expect(scoreKeepingPhrase({ ledger_public: false })).not.toContain("in public");
    expect(scoreKeepingPhrase({ ledger_public: true })).toBe("keeps score in public");
    expect(whoSheIsLine(RULE)).toContain("goes public at launch");
    expect(ledgerRecordSentence({ ...RULE, ledger_public: true })).toContain("is on the ledger");
  });

  it("describes the v2 rule, not v1's mixed evidence", () => {
    const text = whoSheIsLine(RULE) + noForcedCallsSentence(RULE);
    expect(text).not.toMatch(/evidence agrees|data is mixed/);
    expect(noForcedCallsSentence(RULE)).toContain("at most 3 new picks a night");
    expect(noForcedCallsSentence(RULE)).toContain("at most 10 at once");
  });

  it("exit and chain freshness sentences use the rule", () => {
    expect(exitRuleSentence({ ...RULE, exit_trading_days: 7 }, "Sep 30")).toBe("Exit: 7 trading days after earnings (Sep 30)");
    expect(chainFreshnessSentence(RULE)).toContain("more than 2 trading days old");
  });
});

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const full = join(dir, n);
    if (statSync(full).isDirectory()) return n === "__tests__" ? [] : files(full);
    return /\.tsx?$/.test(n) ? [full] : [];
  });
}

describe("no page types Ivy's numbers by hand", () => {
  const COPY = [
    ...files(join(SRC, "app/ivy")), join(SRC, "app/page.tsx"), join(SRC, "app/disclosures/page.tsx"),
    join(SRC, "components/IvyCopy.tsx"), join(SRC, "components/IvyStatLine.tsx"), join(SRC, "lib/ivyRule.ts"),
  ];
  const BANNED: [RegExp, string][] = [
    [/more than 10%|<= ?-10\b|≤ ?-?10%/, "momentum cutoff"],
    [/eight quarters|\b8 quarters/i, "minimum quarters"],
    [/1\.2 ?(times|x|×)/i, "implied move multiple"],
    [/\b5 trading days|five trading days/i, "holding days"],
    [/September 15, 2026|Sep 15, 2026|2026-09-15/, "ledger start date"],
    [/\b3 new picks|\b10 open picks|at most 10 at once/i, "pick caps"],
    [/about 60%|60% of the time/i, "backtest hit rate"],
  ];
  for (const file of COPY) {
    it(file.replace(SRC, "src"), () => {
      const src = readFileSync(file, "utf8");
      for (const [re, what] of BANNED) expect(src, `${what} typed by hand`).not.toMatch(re);
    });
  }
});
