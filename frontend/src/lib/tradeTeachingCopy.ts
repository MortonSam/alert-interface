// Every visitor-facing line of Build a Trade's "What this trade does" panel (Sam, 2026-11-02): DRAFT, held for Sam's approval
// (docs/build_a_trade_wording.md renders it for five trades). The figures come from lib/tradeTeaching, worked out from the trade's
// own legs in code: no model writes any of it. No line tells anyone to buy or sell; each says what the position is and does.

export type StructureKey =
  | "call" | "put" | "call_debit_spread" | "put_debit_spread" | "put_credit_spread" | "call_credit_spread"
  | "straddle" | "strangle" | "covered_call" | "protective_put" | "other";

/** The structure's name, said once, and one sentence on what it is. */
export const STRUCTURES: Record<StructureKey, { name: string; explain: string }> = {
  call: { name: "a call", explain: "A call is the right to buy 100 shares at its strike price until expiration; it gains when the stock ends above the strike price by more than the call cost." },
  put: { name: "a put", explain: "A put is the right to sell 100 shares at its strike price until expiration; it gains when the stock ends below the strike price by more than the put cost." },
  call_debit_spread: { name: "a call spread", explain: "A call spread is buying one call and selling another with a higher strike price: the call sold lowers the cost and caps the gain." },
  put_debit_spread: { name: "a put spread", explain: "A put spread is buying one put and selling another with a lower strike price: the put sold lowers the cost and caps the gain." },
  put_credit_spread: { name: "a put credit spread", explain: "A put credit spread is selling one put and buying another with a lower strike price: the cash comes in at the start, and the put bought caps the loss." },
  call_credit_spread: { name: "a call credit spread", explain: "A call credit spread is selling one call and buying another with a higher strike price: the cash comes in at the start, and the call bought caps the loss." },
  straddle: { name: "a straddle", explain: "A straddle is buying a call and a put with the same strike price and expiration: it gains when the stock moves far enough either way to cover both." },
  strangle: { name: "a strangle", explain: "A strangle is buying a call with a higher strike price and a put with a lower one: it costs less than a straddle and needs a bigger move either way." },
  covered_call: { name: "a covered call", explain: "A covered call is owning 100 shares and selling a call on them: the call brings in cash now, and any rise above its strike price goes to the call's owner instead." },
  protective_put: { name: "a protective put", explain: "A protective put is owning 100 shares and buying a put on them: the put sets a floor under the shares until expiration, for what it costs." },
  other: { name: "this combination", explain: "Its result at expiration is worked out below from each of its parts." },
};

export const PANEL_TITLE = "What this trade does";

/** Each line of the panel, filled from figures the code works out (money and prices already formatted). */
export const LINES = {
  intro: (name: string, explain: string) => `This is ${name}. ${explain}`,
  paySingle: (total: string, perShare: string) => `You pay ${total} at the start: ${perShare} a share, for 100 shares.`,
  payDebit: (total: string, perShare: string) => `You pay ${total} at the start: a net debit of ${perShare} a share, for 100 shares.`,
  receiveCredit: (total: string, perShare: string) => `You receive ${total} at the start: a net credit of ${perShare} a share, for 100 shares.`,
  shares: (basis: string) => `It assumes 100 shares held at ${basis}.`,
  betAbove: (sym: string, level: string, date: string) => `It gains if ${sym} ends above ${level} at expiration on ${date}.`,
  betBelow: (sym: string, level: string, date: string) => `It gains if ${sym} ends below ${level} at expiration on ${date}.`,
  betOutside: (sym: string, lo: string, hi: string, date: string) => `It gains if ${sym} ends below ${lo} or above ${hi} at expiration on ${date}: a big enough move either way.`,
  betInside: (sym: string, lo: string, hi: string, date: string) => `It gains if ${sym} ends between ${lo} and ${hi} at expiration on ${date}.`,
  breakevenFrom: (level: string, ref: string, refKind: "strike price" | "share price", plus: boolean, cash: string, paid: boolean) =>
    `The breakeven is ${level}: the ${ref} ${refKind} ${plus ? "plus" : "minus"} the ${cash} a share ${paid ? "paid" : "received"}.`,
  breakeven: (level: string) => `The breakeven is ${level}, where the result at expiration is zero.`,
  breakevens: (lo: string, hi: string) => `There are two breakevens, ${lo} and ${hi}: the result at expiration is zero at each.`,
  capAt: (level: string, most: string) => `The gain stops growing at ${level}: past it, the most the trade can make is ${most}.`,
  noCapUp: "There is no cap on the gain: it keeps growing as the stock rises.",
  noCapUpAndDown: (most: string) => `There is no cap on the gain as the stock rises; as it falls, the gain grows up to ${most} if it reached $0.`,
  capAtZero: (most: string) => `The gain keeps growing as the stock falls, up to ${most} if it reached $0.`,
  maxLossPaid: (loss: string) => `The most it can lose is ${loss}, the amount paid.`,
  maxLoss: (loss: string, at: string) => `The most it can lose is ${loss}, if it ends ${at}.`,
  maxLossOpen: "There is no limit to how much it can lose as the stock rises.",
  atExpiration: (date: string) => `At expiration on ${date}:`,
} as const;

/** One stretch of stock prices at expiration and what the trade is worth there. */
export const REGIONS = {
  above: (level: string) => `Above ${level}`,
  between: (lo: string, hi: string) => `Between ${lo} and ${hi}`,
  below: (level: string) => `Below ${level}`,
  flat: (range: string, result: string) => `${range}: ${result}, wherever it ends in that range.`,
  sloped: (range: string, perDollar: string, way: "grows" | "drops", from: string, a: string, to: string, b: string) =>
    `${range}: the result ${way} by ${perDollar} for every $1 the stock rises, from ${from} at ${a} to ${to} at ${b}.`,
  open: (range: string, perDollar: string, from: string, a: string) =>
    `${range}: the result grows by ${perDollar} for every $1 the stock rises past ${a}, from ${from} there.`,
};

export const RESULT = {
  gain: (x: string) => `a ${x} gain`,
  loss: (x: string) => `a ${x} loss`,
  zero: "no gain or loss",
};
