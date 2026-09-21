// Ivy's copy, built from data. No page types her thresholds, her backtest
// results or her ledger's start date: they come from GET /theses/ivy-rule, which
// the backend builds from ivy_v2.py, constants.py and the stored backtest run.

export interface IvyRule {
  momentum_cutoff_pct: number;        // -10: qualifies at or below this 20-day return
  momentum_lookback_days: number;
  min_prior_quarters: number;
  implied_move_multiple: number;
  exit_trading_days: number;
  candidate_window_days: number;
  max_new_picks_per_night: number;
  max_open_picks: number;
  ledger_start: string;               // YYYY-MM-DD
  ledger_public: boolean;
  chain_fresh_trading_days: number;
}

export interface IvyBacktestFold {
  label: string;                      // "2023", "2025-26"
  setups: number;
  hits: number;
  hit_rate: number | null;            // 0-1
  base_n: number;
  base_rate: number | null;           // 0-1
}

export interface IvyBacktest {
  as_of_date: string;
  run_at: string;
  folds: IvyBacktestFold[];
  setups: number;
  hits: number;
  hit_rate: number;
  base_n: number;
  base_rate: number;
  passed: boolean;
}

export interface IvyRuleResponse {
  rule: IvyRule;
  backtest: IvyBacktest | null;
}

const pct = (rate: number) => (rate * 100).toFixed(1);

export function fmtLongDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function joinYears(labels: string[]): string {
  if (labels.length <= 1) return labels.join("");
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

/** How the rule has done outside its best fold, in words that follow the numbers. */
export function restOfRecordPhrase(backtest: IvyBacktest, bestIndex: number): string {
  const rest = backtest.folds.filter((_, i) => i !== bestIndex && _.setups > 0 && _.base_n > 0);
  const setups = rest.reduce((a, f) => a + f.setups, 0);
  const hits = rest.reduce((a, f) => a + f.hits, 0);
  const baseN = rest.reduce((a, f) => a + f.base_n, 0);
  const baseUps = rest.reduce((a, f) => a + (f.base_rate ?? 0) * f.base_n, 0);
  const lead = bestIndex === 0 ? "Since then" : "In the other years";
  if (!setups || !baseN) return `${lead} there are too few setups to say.`;
  const liftPts = (hits / setups - baseUps / baseN) * 100;
  if (liftPts < -0.5) return `${lead} it has been below the base rate.`;
  if (liftPts < 0.5) return `${lead} it has been close to zero.`;
  if (liftPts < 1.5) return `${lead} it has been about a point.`;
  return `${lead} it has been about ${Math.round(liftPts)} points.`;
}

/** The "One rule" paragraph on /ivy. Every number is a slot filled from the API. */
export function oneRuleParagraph(rule: IvyRule, backtest: IvyBacktest | null): string {
  const setup =
    `Ivy looks for one setup. A company reports earnings in the next few days, its stock has fallen more than ` +
    `${Math.abs(rule.momentum_cutoff_pct)}% over the prior ${rule.momentum_lookback_days} trading days, and it has at least ` +
    `${rule.min_prior_quarters} quarters of earnings history.`;

  let tested = "";
  if (backtest && backtest.setups > 0) {
    const scored = backtest.folds.map((f, i) => ({ f, i, lift: (f.hit_rate ?? 0) - (f.base_rate ?? 0) }));
    const best = scored.reduce((a, b) => (b.lift > a.lift ? b : a));
    tested =
      ` That rule was tested against ${joinYears(backtest.folds.map((f) => f.label))}.` +
      ` Across ${backtest.setups} setups the stock was higher five days later ${pct(backtest.hit_rate)}% of the time,` +
      ` against ${pct(backtest.base_rate)}% for all earnings reports in those years.` +
      ` That edge is small, and most of it came in ${best.f.label}` +
      ` (${pct(best.f.hit_rate ?? 0)}% against ${pct(best.f.base_rate ?? 0)}%).` +
      ` ${restOfRecordPhrase(backtest, best.i)}` +
      ` Those years chose the rule as much as tested it, so the only test that counts is the live record,` +
      ` kept since ${fmtLongDate(rule.ledger_start)}. A small edge you can check beats a large one you can't.`;
  } else {
    tested =
      ` The only test that counts is the live record, kept since ${fmtLongDate(rule.ledger_start)}.` +
      ` A small edge you can check beats a large one you can't.`;
  }

  const gate =
    ` Before she buys anything, Ivy checks what the options market is pricing. If the implied move is more than ` +
    `${rule.implied_move_multiple} times the stock's usual earnings move, she refuses. Every pick carries its receipt, ` +
    `with the number of comparable setups, the base rate, the expected move, and what the options were pricing. ` +
    `She makes no bearish calls. The data has not earned them yet.`;

  return setup + tested + gate;
}

/** "keeps score in public" is only true once the ledger is public. */
export function scoreKeepingPhrase(rule: Pick<IvyRule, "ledger_public">): string {
  return rule.ledger_public ? "keeps score in public" : "keeps score on a ledger that goes public at launch";
}

export function whoSheIsLine(rule: IvyRule): string {
  return `She reads the tape overnight, makes a call only when her one setup appears, and ${scoreKeepingPhrase(rule)}.`;
}

/** v2 has one rule and no "mixed evidence" state. */
export function noForcedCallsSentence(rule: IvyRule): string {
  return (
    `She passes when the setup is absent: no ${Math.abs(rule.momentum_cutoff_pct)}% drop, or fewer than ` +
    `${rule.min_prior_quarters} quarters of history, means no pick. She opens at most ${rule.max_new_picks_per_night} ` +
    `new picks a night and holds at most ${rule.max_open_picks} at once.`
  );
}

export function ledgerRecordSentence(rule: IvyRule): string {
  const since = fmtLongDate(rule.ledger_start);
  return rule.ledger_public
    ? `Every pick since ${since} is on the ledger, losses next to wins.`
    : `Every pick since ${since} is recorded the night it is made. The ledger goes public at launch.`;
}

export function exitRuleSentence(rule: IvyRule, exitDate?: string | null): string {
  return `Exit: ${rule.exit_trading_days} trading days after earnings${exitDate ? ` (${exitDate})` : ""}`;
}

export function chainFreshnessSentence(rule: IvyRule): string {
  return (
    `Options data is uploaded once a day. A chain more than ${rule.chain_fresh_trading_days} trading days old is not used, ` +
    `so a name can show no implied move even when it has options.`
  );
}
