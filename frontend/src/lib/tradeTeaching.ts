// Build a Trade's "What this trade does" panel, worked out from the trade's own legs (Sam, 2026-11-02): what is paid or received,
// what the trade bets on and by when, its breakeven, where the gain stops growing, the most it can lose, and its result at
// expiration in each stretch of stock prices. Pure arithmetic on the legs (payoff at expiration, per 100 shares); no model call.
// The words are lib/tradeTeachingCopy's.

import { fmtDate } from "@/lib/dates";
import { LINES, REGIONS, RESULT, STRUCTURES, type StructureKey } from "@/lib/tradeTeachingCopy";

export interface TeachLeg {
  type: "call" | "put" | "stock";
  side: "long" | "short";
  strike?: number;        // options only
  price: number;          // per share: the option's premium, or the price the shares are held at
}

export interface TeachPanel {
  structure: StructureKey;
  lines: string[];        // intro, cash, bet, breakeven, cap, most it can lose
  expirationLine: string;
  regions: string[];      // above the highest strike first, then down
}

const SHARES = 100;

const money = (x: number) => `$${Math.round(Math.abs(x)).toLocaleString("en-US")}`;
const price = (x: number) => `$${x.toFixed(2).replace(/\.00$/, "")}`;
const perShare = (x: number) => `$${Math.abs(x).toFixed(2)}`;

/** "an $800 gain", "a $640 gain": the article as the amount is spoken. */
function article(amount: string, phrase: string): string {
  const digits = amount.replace(/[^0-9]/g, "");
  const an = digits.startsWith("8") || (digits.length % 3 === 2 && (digits.startsWith("11") || digits.startsWith("18")));
  return an ? phrase.replace(/^a /, "an ") : phrase;
}

function result(x: number): string {
  const r = Math.round(x);
  if (r === 0) return RESULT.zero;
  return r > 0 ? article(money(r), RESULT.gain(money(r))) : article(money(r), RESULT.loss(money(r)));
}

/** The trade's value at expiration at stock price S, for 100 shares. */
export function payoffAt(legs: TeachLeg[], S: number): number {
  return SHARES * legs.reduce((sum, l) => {
    const sign = l.side === "long" ? 1 : -1;
    if (l.type === "stock") return sum + sign * (S - l.price);
    const intrinsic = l.type === "call" ? Math.max(0, S - (l.strike as number)) : Math.max(0, (l.strike as number) - S);
    return sum + sign * (intrinsic - l.price);
  }, 0);
}

/** Dollars gained per $1 the stock rises above every strike (100 x calls long minus calls short, plus shares held). */
function slopeAbove(legs: TeachLeg[]): number {
  return SHARES * legs.reduce((s, l) => s + (l.type === "put" ? 0 : l.side === "long" ? 1 : -1), 0);
}

export function classify(legs: TeachLeg[]): StructureKey {
  const opts = legs.filter((l) => l.type !== "stock");
  const stock = legs.filter((l) => l.type === "stock");
  const cash = opts.reduce((s, l) => s + (l.side === "long" ? -l.price : l.price), 0);
  if (stock.length === 1 && stock[0].side === "long" && opts.length === 1) {
    if (opts[0].type === "call" && opts[0].side === "short") return "covered_call";
    if (opts[0].type === "put" && opts[0].side === "long") return "protective_put";
  }
  if (stock.length) return "other";
  if (opts.length === 1 && opts[0].side === "long") return opts[0].type as "call" | "put";
  if (opts.length === 2) {
    const [a, b] = opts;
    if (a.type === b.type && a.side !== b.side) {
      if (a.type === "call") return cash < 0 ? "call_debit_spread" : "call_credit_spread";
      return cash < 0 ? "put_debit_spread" : "put_credit_spread";
    }
    if (a.type !== b.type && a.side === "long" && b.side === "long") {
      const call = opts.find((l) => l.type === "call")!, put = opts.find((l) => l.type === "put")!;
      if (call.strike === put.strike) return "straddle";
      if ((call.strike as number) > (put.strike as number)) return "strangle";
    }
  }
  return "other";
}

/** The panel for a trade: `symbol`, its legs, and the expiration date (YYYY-MM-DD). */
export function teachPanel(symbol: string, legs: TeachLeg[], expiration: string): TeachPanel {
  const structure = classify(legs);
  const { name, explain } = STRUCTURES[structure];
  const date = fmtDate(expiration) ?? expiration;
  const opts = legs.filter((l) => l.type !== "stock");
  const stock = legs.find((l) => l.type === "stock");
  const strikes = [...new Set(opts.map((l) => l.strike as number))].sort((a, b) => a - b);
  const cashPerShare = opts.reduce((s, l) => s + (l.side === "long" ? -l.price : l.price), 0);   // < 0: paid; > 0: received
  const lines: string[] = [LINES.intro(name, explain)];

  // what is paid or received
  if (cashPerShare < 0) {
    lines.push(opts.length === 1 && !stock ? LINES.paySingle(money(cashPerShare * SHARES), perShare(cashPerShare)) : LINES.payDebit(money(cashPerShare * SHARES), perShare(cashPerShare)));
  } else if (cashPerShare > 0) {
    lines.push(LINES.receiveCredit(money(cashPerShare * SHARES), perShare(cashPerShare)));
  }
  if (stock) lines.push(LINES.shares(price(stock.price)));

  // the shape: the value at $0, at each strike, and the slope past the highest
  const knots = [0, ...strikes];
  const values = knots.map((k) => payoffAt(legs, k));
  const up = slopeAbove(legs);
  // breakevens: where a straight piece between two knots (or past the last) crosses zero
  const bes: number[] = [];
  for (let i = 0; i + 1 < knots.length; i++) {
    const [a, b, fa, fb] = [knots[i], knots[i + 1], values[i], values[i + 1]];
    if ((fa < 0 && fb > 0) || (fa > 0 && fb < 0)) bes.push(a + (b - a) * (-fa / (fb - fa)));
  }
  const last = knots[knots.length - 1], fLast = values[values.length - 1];
  if ((fLast < 0 && up > 0) || (fLast > 0 && up < 0)) bes.push(last - fLast / up);

  // the bet
  const gainAbove = up > 0 || (up === 0 && fLast > 0);
  const gainAtZero = values[0] > 0;
  if (bes.length === 1) lines.push(gainAbove ? LINES.betAbove(symbol, price(bes[0]), date) : LINES.betBelow(symbol, price(bes[0]), date));
  else if (bes.length === 2) lines.push(gainAbove && gainAtZero ? LINES.betOutside(symbol, price(bes[0]), price(bes[1]), date) : LINES.betInside(symbol, price(bes[0]), price(bes[1]), date));

  // the breakeven, from a strike and the cash when that is what it is
  if (bes.length === 1) {
    const be = bes[0];
    // the strike (or, with shares, the price they are held at) the breakeven sits the cash away from
    const refs: { k: number; kind: "strike price" | "share price" }[] = [...strikes.map((k) => ({ k, kind: "strike price" as const })),
                                                                         ...(stock ? [{ k: stock.price, kind: "share price" as const }] : [])];
    const from = refs.map((r) => ({ ...r, d: be - r.k })).find(({ d }) => Math.abs(Math.abs(d) - Math.abs(cashPerShare)) < 0.005);
    lines.push(from && cashPerShare !== 0 ? LINES.breakevenFrom(price(be), price(from.k), from.kind, from.d > 0, perShare(cashPerShare), cashPerShare < 0) : LINES.breakeven(price(be)));
  } else if (bes.length === 2) {
    lines.push(LINES.breakevens(price(bes[0]), price(bes[1])));
  }

  // where the gain stops growing
  const best = Math.max(...values, up === 0 ? fLast : -Infinity);
  if (up > 0) lines.push(values[0] > 0 ? LINES.noCapUpAndDown(money(values[0])) : LINES.noCapUp);
  else if (values[0] === best && values[0] > 0 && strikes.length === 1 && opts.length === 1) lines.push(LINES.capAtZero(money(best)));
  else if (best > 0) {
    const at = knots.slice(1).find((k, i) => values[i + 1] === best) ?? last;
    lines.push(LINES.capAt(price(at), money(best)));
  }

  // the most it can lose
  if (up < 0) lines.push(LINES.maxLossOpen);
  else {
    const worst = Math.min(...values, up === 0 ? fLast : Infinity);
    if (worst < 0) {
      if (Math.abs(Math.round(-worst) - Math.round(-cashPerShare * SHARES)) <= 1 && cashPerShare < 0 && !stock) lines.push(LINES.maxLossPaid(money(worst)));
      else {
        // where it is reached: a flat stretch from $0 ("at or below"), a flat top ("at or above"), or one price
        const at = (() => {
          const hits = values.map((v, i) => (Math.round(v) === Math.round(worst) ? i : -1)).filter((i) => i >= 0);
          const hi = hits[hits.length - 1];
          if (hits[0] === 0 && hi > 0) return `at or below ${price(knots[hi])}`;
          if (hi === values.length - 1 && up === 0 && hi > 0) return `at or above ${price(knots[hi])}`;
          return hi === 0 ? "at $0" : `at ${price(knots[hi])}`;
        })();
        lines.push(LINES.maxLoss(money(worst), at));
      }
    }
  }

  // the result at expiration in each stretch, from the top down
  const regions: string[] = [];
  const range = (a: number, b: number | null) => (b == null ? REGIONS.above(price(a)) : a === 0 ? REGIONS.below(price(b)) : REGIONS.between(price(a), price(b)));
  const describe = (a: number, b: number | null, fa: number, fb: number | null) => {
    const label = range(a, b);
    if (b == null) return up === 0 ? REGIONS.flat(label, result(fa)) : REGIONS.open(label, money(up), result(fa), price(a));
    if (Math.round(fa) === Math.round(fb as number)) return REGIONS.flat(label, result(fa));
    const perDollar = money(((fb as number) - fa) / (b - a));
    return REGIONS.sloped(label, perDollar, (fb as number) > fa ? "grows" : "drops", result(fa), a === 0 ? "$0" : price(a), result(fb as number), price(b));
  };
  if (strikes.length) regions.push(describe(last, null, fLast, null));
  for (let i = knots.length - 2; i >= 0; i--) regions.push(describe(knots[i], knots[i + 1], values[i], values[i + 1]));

  return { structure, lines, expirationLine: LINES.atExpiration(date), regions };
}
