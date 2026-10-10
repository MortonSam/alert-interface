// The home page's three proof cards: the product working, from the endpoints the rest of the site already reads (Discover's
// reporting-soon and unusually-active lists, the ticker page's expected move, Ivy's activity). No figure is typed here and none
// comes from Discover news, which is behind its flag. A card without its data is left out, never filled with a guess.
import type { ExpectedMove, IvyActivity, ReportingSoonItem, UnusuallyActiveItem } from "@/lib/api";
import { fmtIsoDateTime } from "@/lib/freshness";
import { fmtMovePct } from "@/lib/newsSections";

export interface ProofCard {
  key: string;
  kicker: string;          // what the card shows, in a few words
  title: string;           // the stock or the subject
  value: string;           // the one number
  tone: "accent" | "up" | "down" | "plain";
  lines: string[];         // context, each from the same response
  asOf: string;            // the data's own date, never the request time
  href: string;
}

/** "Oct 13" from a YYYY-MM-DD date, read as a calendar date. */
export function fmtDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const money = (n: number) => `$${n.toFixed(2)}`;

/** The soonest report the options are pricing (reporting-soon's order), with the range from the ticker page's expected move. */
export function earningsCard(items: ReportingSoonItem[] | null, em: ExpectedMove | null): ProofCard | null {
  const item = (items ?? []).find((i) => i.implied_move_pct != null && i.chain_date);
  if (!item || item.implied_move_pct == null || !item.chain_date) return null;
  const lines: string[] = [];
  const sameChain = em && em.symbol === item.symbol && em.chain_date === item.chain_date;
  if (sameChain && em.quote_state === "ok" && em.implied_range_low != null && em.implied_range_high != null && em.expiration_used) {
    lines.push(`${money(em.implied_range_low)} to ${money(em.implied_range_high)} by ${fmtDay(em.expiration_used)}`);
  }
  if (item.typical_move_pct != null && item.typical_n) lines.push(`Usual earnings move ±${item.typical_move_pct.toFixed(1)}% over ${item.typical_n} reports`);
  const when = item.confirmation === "confirmed" ? `reports ${fmtDay(item.earnings_date)}` : `expected to report ${fmtDay(item.earnings_date)}`;
  return {
    key: "earnings", kicker: "Options are pricing", title: `${item.symbol} ${when}`,
    value: `±${item.implied_move_pct.toFixed(1)}%`, tone: "accent", lines,
    asOf: `Options chain of ${fmtDay(item.chain_date)}`, href: `/tickers/${item.symbol}`,
  };
}

/** Ivy's latest nightly run: when it ran and, where the API shares it, what she evaluated. */
export function ivyCard(a: IvyActivity | null): ProofCard | null {
  if (!a?.last_run_at) return null;
  const when = fmtIsoDateTime(a.last_run_at);
  if (!when) return null;
  const lines: string[] = [];
  if (a.run_date && a.evaluated > 0) lines.push(`${a.evaluated} names evaluated, ${a.picked} picked`);
  lines.push(a.last_run_failed ? "The run did not complete" : "The run completed");
  return {
    key: "ivy", kicker: "Ivy's last nightly run", title: "Her one rule, applied",
    value: when.split(",")[0], tone: "plain", lines, asOf: `Recorded ${when}`, href: "/ivy/desk",
  };
}

/** The first stock on Discover's unusually-active list, with the session behind its volatility when one dominates. */
export function unusualCard(items: UnusuallyActiveItem[] | null): ProofCard | null {
  const item = (items ?? []).find((i) => i.dominant_move_pct != null && i.dominant_date) ?? (items ?? [])[0];
  if (!item) return null;
  const dominant = item.dominant_move_pct != null && item.dominant_date;
  const asOfDate = dominant ? item.dominant_date : item.iv_date;
  if (!asOfDate) return null;
  return {
    key: "unusual", kicker: "Moving unusually", title: item.name ?? item.symbol,
    value: dominant ? fmtMovePct(item.dominant_move_pct as number) : `RV rank ${Math.round(item.rv_rank)}`,
    tone: dominant ? ((item.dominant_move_pct as number) >= 0 ? "up" : "down") : "plain",
    lines: [dominant ? `${item.symbol} on ${fmtDay(item.dominant_date as string)}, RV rank ${Math.round(item.rv_rank)}, ${item.tier}` : (item.insight ?? item.symbol)],
    asOf: dominant ? `Session of ${fmtDay(asOfDate)}` : `Options chain of ${fmtDay(asOfDate)}`, href: `/tickers/${item.symbol}`,
  };
}
