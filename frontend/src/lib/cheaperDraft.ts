// Build a Trade's words when the options on a stock are expensive compared with how much it usually moves (backend
// ivy_v2.vol_gate_trips, the same rule Ivy's own picks use). The customer still gets a draft: a cheaper defined-risk spread in the
// direction they chose. Every figure comes from the draft's stored chain.
import type { ThesisDraftRead } from "@/lib/api";

const usd = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;

/** After Ivy declines her own pick on expensive options: the customer picks a direction and gets the cheaper draft. */
export function expensiveOptionsPrompt(symbol: string): string {
  return `The options on ${symbol} are expensive right now compared with how much the stock usually moves. Pick a direction and the draft will be a cheaper way to make that bet.`;
}

/** Above the cheaper draft. */
export function expensiveOptionsLine(symbol: string): string {
  return `The options on ${symbol} are expensive right now compared with how much the stock usually moves, so the draft below is a cheaper way to make the same bet.`;
}

/** "This spread costs $780 per contract. Buying the $300 call outright would cost $1,300." Null without both prices. */
export function cheaperCostLine(draft: ThesisDraftRead, spreadCostPerContract: number | null): string | null {
  const x = draft.options_expensive;
  if (!x || spreadCostPerContract == null || !(x.outright_mid > 0)) return null;
  return `This spread costs ${usd(spreadCostPerContract)} per contract. Buying the $${x.outright_strike} ${x.outright_kind} outright would cost ${usd(x.outright_mid * 100)}.`;
}
