// Every visitor-facing line of Build a Trade's "What this trade does" panel (Sam, 2026-11-02), approved by Sam on Nov 2
// (docs/build_a_trade_wording.md renders it for five trades). The figures come from lib/tradeTeaching, worked out from the trade's
// own legs in code, and no model writes any of it. No line has a colon (Sam, 2026-11-02). No line tells anyone to buy or sell; each says what the position is and does.

export type StructureKey =
  | "call" | "put" | "call_debit_spread" | "put_debit_spread" | "put_credit_spread" | "call_credit_spread"
  | "straddle" | "strangle" | "covered_call" | "protective_put" | "other";

/** The structure's name, said once, and one sentence on what it is. */
export const STRUCTURES: Record<StructureKey, { name: string; explain: string }> = {
  call: { name: "a call", explain: "A call is the right to buy 100 shares at its strike price until expiration; it gains when the stock ends above the strike price by more than the call cost." },
  put: { name: "a put", explain: "A put is the right to sell 100 shares at its strike price until expiration; it gains when the stock ends below the strike price by more than the put cost." },
  call_debit_spread: { name: "a call spread", explain: "A call spread is buying one call and selling another with a higher strike price. The call sold lowers the cost and caps the gain." },
  put_debit_spread: { name: "a put spread", explain: "A put spread is buying one put and selling another with a lower strike price. The put sold lowers the cost and caps the gain." },
  put_credit_spread: { name: "a put credit spread", explain: "A put credit spread is selling one put and buying another with a lower strike price. The cash comes in at the start, and the put bought caps the loss." },
  call_credit_spread: { name: "a call credit spread", explain: "A call credit spread is selling one call and buying another with a higher strike price. The cash comes in at the start, and the call bought caps the loss." },
  straddle: { name: "a straddle", explain: "A straddle is buying a call and a put with the same strike price and expiration. It gains when the stock moves far enough either way to cover both." },
  strangle: { name: "a strangle", explain: "A strangle is buying a call with a higher strike price and a put with a lower one. It costs less than a straddle and needs a bigger move either way." },
  covered_call: { name: "a covered call", explain: "A covered call is owning 100 shares and selling a call on them. The call brings in cash now, and any rise above its strike price goes to the call's owner instead." },
  protective_put: { name: "a protective put", explain: "A protective put is owning 100 shares and buying a put on them. The put sets a floor under the shares until expiration, for what it costs." },
  other: { name: "this combination", explain: "Its result at expiration is worked out below from each of its parts." },
};

export const PANEL_TITLE = "What this trade does";

/** Each line of the panel, filled from figures the code works out (money and prices already formatted). */
export const LINES = {
  intro: (name: string, explain: string) => `This is ${name}. ${explain}`,
  pay: (total: string, perShare: string) => `Option prices are quoted per share, and one contract covers 100 shares, so you pay ${total} at the start (${perShare} a share).`,
  receive: (total: string, perShare: string) => `Option prices are quoted per share, and one contract covers 100 shares, so you receive ${total} at the start (${perShare} a share).`,
  coveredCallDoing: (sym: string, strike: string) =>
    `You own 100 shares and sell someone the right to buy them from you at ${strike}, which brings in cash now. If ${sym} ends above ${strike}, you sell at ${strike} and miss any rise past it.`,
  shares: (basis: string) => `It assumes 100 shares held at ${basis}.`,
  betAbove: (sym: string, level: string, date: string) => `It gains if ${sym} ends above ${level} at expiration on ${date}.`,
  betBelow: (sym: string, level: string, date: string) => `It gains if ${sym} ends below ${level} at expiration on ${date}.`,
  betOutside: (sym: string, lo: string, hi: string, date: string) => `It gains if ${sym} ends below ${lo} or above ${hi} at expiration on ${date}, a big enough move either way.`,
  betInside: (sym: string, lo: string, hi: string, date: string) => `It gains if ${sym} ends between ${lo} and ${hi} at expiration on ${date}.`,
  breakevenFrom: (level: string, ref: string, refKind: "strike price" | "share price", plus: boolean, cash: string, paid: boolean) =>
    `The breakeven is ${level}, the ${ref} ${refKind} ${plus ? "plus" : "minus"} the ${cash} a share ${paid ? "paid" : "received"}.`,
  breakeven: (level: string) => `The breakeven is ${level}, where the result at expiration is zero.`,
  breakevens: (lo: string, hi: string) => `There are two breakevens, ${lo} and ${hi}, and the result at expiration is zero at each.`,
  keepCredit: (credit: string, sym: string, where: "above" | "below", level: string) => `You keep the full ${credit} if ${sym} ends ${where} ${level}.`,
  mostAt: (most: string, sym: string, level: string) => `The most it can make is ${most}, if ${sym} ends at or above ${level}.`,
  capAt: (level: string, most: string) => `The gain stops growing at ${level}. Past it, the most the trade can make is ${most}.`,
  noCapUp: "There is no cap on the gain. It keeps growing as the stock rises.",
  noCapUpAndDown: (most: string) => `There is no cap on the gain as the stock rises; as it falls, the gain grows up to ${most} if it reached $0.`,
  capAtZero: (most: string) => `The gain keeps growing as the stock falls, up to ${most} if it reached $0.`,
  maxLossPaid: (loss: string) => `The most it can lose is ${loss}, the amount paid.`,
  maxLoss: (loss: string, at: string) => `The most it can lose is ${loss}, if it ends ${at}.`,
  maxLossShares: (sym: string, loss: string, saved: string) => `If ${sym} fell to $0, you would lose ${loss}, which is ${saved} less than owning the shares alone.`,
  maxLossOpen: "There is no limit to how much it can lose as the stock rises.",
  atExpiration: (date: string) => `At expiration on ${date}`,
  closeEarly: "You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.",
} as const;

/** One stretch of stock prices at expiration and what the trade is worth there. */
/** One stretch of stock prices at expiration and what the trade is worth there. Every breakeven bounds a stretch, so each stretch
 *  is all gain or all loss, told the way a person thinks: a gain grows as the stock moves the trade's way, and a loss is largest
 *  at the end farthest from the breakeven (or grows to $0, when nothing floors it above $0). */
export const REGIONS = {
  above: (level: string) => `Above ${level}`,
  between: (lo: string, hi: string) => `Between ${lo} and ${hi}`,
  below: (level: string) => `Below ${level}`,
  flat: (range: string, result: string) => `${range}, ${result}, wherever it ends in that range.`,
  gainGrows: (range: string, perDollar: string, way: "higher" | "lower") => `${range}, the gain grows by ${perDollar} for every $1 ${way}.`,
  gainGrowsTo: (range: string, perDollar: string, way: "higher" | "lower", most: string, at: string) =>
    `${range}, the gain grows by ${perDollar} for every $1 ${way}, up to ${most} at ${at}.`,
  lossShrinks: (range: string, way: "rises" | "falls", at: string, loss: string) => `${range}, a loss that shrinks as the stock ${way}, largest at ${at} (${loss}).`,
  lossGrowsToZero: (range: string, perDollar: string, loss: string) => `${range}, the loss grows by ${perDollar} for every $1 lower, up to ${loss} at $0.`,
  lossGrowsOpen: (range: string, perDollar: string) => `${range}, the loss grows by ${perDollar} for every $1 higher, with no limit.`,
};

export const RESULT = {
  gain: (x: string) => `a ${x} gain`,
  loss: (x: string) => `a ${x} loss`,
  zero: "no gain or loss",
};
