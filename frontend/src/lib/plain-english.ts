// ── Plain-English reasoning builder (deterministic, no LLM) ──────────────────

export function buildPlainEnglish(opts: {
  shortName: string;
  direction: string;
  isSpread: boolean;
  symbol: string;
  strike: number | null;
  spreadStrike: number | null;
  cost: number | null;
  maxLoss: number | null;
  maxGain: number | "unlimited" | null;
  netDebit: number | null;
  breakeven: number | null;
  expiration: string | null;
}): string | null {
  const { shortName, direction, isSpread, symbol, strike, spreadStrike, cost, maxLoss, maxGain, netDebit, breakeven, expiration } = opts;
  if (cost == null || maxLoss == null || strike == null) return null;

  const $w = (n: number) => `$${Math.round(n)}`;                 // whole-dollar
  const $d = (n: number) => `$${n.toFixed(2)}`;                  // 2-decimal
  const exp = expiration ? ` at expiration on ${expiration}` : " at expiration";
  const sentences: string[] = [];

  if (isSpread && direction === "bullish") {
    // ── Bull call spread ──
    sentences.push(`This is a ${shortName.toLowerCase()} on ${symbol} — a bet the stock rises, with both cost and risk capped.`);
    if (spreadStrike != null)
      sentences.push(`You buy the $${strike} call and sell the $${spreadStrike} call, paying ${$w(cost)} up front${netDebit != null ? ` (net debit ${$d(netDebit)}/share)` : ""}.`);
    sentences.push(`That ${$w(maxLoss)} is the most you can lose.`);
    if (maxGain != null && maxGain !== "unlimited" && spreadStrike != null)
      sentences.push(`If ${symbol} closes above $${spreadStrike}${exp}, you make the most you can: ${$w(maxGain)}.`);
    if (breakeven != null)
      sentences.push(`You start making money above ${$d(breakeven)} (breakeven).`);
    sentences.push(`Below $${strike} the spread expires worthless and you lose the full ${$w(maxLoss)}.`);

  } else if (isSpread && direction === "bearish") {
    // ── Bear put spread ──
    sentences.push(`This is a ${shortName.toLowerCase()} on ${symbol} — a bet the stock falls, with both cost and risk capped.`);
    if (spreadStrike != null)
      sentences.push(`You buy the $${strike} put and sell the $${spreadStrike} put, paying ${$w(cost)} up front${netDebit != null ? ` (net debit ${$d(netDebit)}/share)` : ""}.`);
    sentences.push(`That ${$w(maxLoss)} is the most you can lose.`);
    if (maxGain != null && maxGain !== "unlimited" && spreadStrike != null)
      sentences.push(`If ${symbol} closes below $${spreadStrike}${exp}, you make the most you can: ${$w(maxGain)}.`);
    if (breakeven != null)
      sentences.push(`You start making money below ${$d(breakeven)} (breakeven).`);
    sentences.push(`Above $${strike} the spread expires worthless and you lose the full ${$w(maxLoss)}.`);

  } else if (!isSpread && direction === "bullish") {
    // ── Long call (unlimited upside) ──
    sentences.push(`This is a ${shortName.toLowerCase()} on ${symbol} — a leveraged bet the stock rises.`);
    sentences.push(`You pay ${$w(cost)} for the $${strike} call. That total cost is the most you can lose.`);
    sentences.push(`Your upside is uncapped — the higher ${symbol} goes above $${strike}${exp}, the more you make.`);
    if (breakeven != null)
      sentences.push(`You start making money above ${$d(breakeven)} (breakeven).`);
    sentences.push(`Below $${strike} the call expires worthless and you lose the full ${$w(maxLoss)}.`);

  } else {
    // ── Long put ──
    sentences.push(`This is a ${shortName.toLowerCase()} on ${symbol} — a leveraged bet the stock falls.`);
    sentences.push(`You pay ${$w(cost)} for the $${strike} put. That total cost is the most you can lose.`);
    if (maxGain != null && maxGain !== "unlimited")
      sentences.push(`If ${symbol} drops to zero${exp}, you make the most you can: ${$w(maxGain)}.`);
    if (breakeven != null)
      sentences.push(`You start making money below ${$d(breakeven)} (breakeven).`);
    sentences.push(`Above $${strike} the put expires worthless and you lose the full ${$w(maxLoss)}.`);
  }

  return sentences.join(" ");
}
