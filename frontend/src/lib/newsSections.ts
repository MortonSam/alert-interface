// Discover's news sections: the words they print. A headline beside a move is labelled "In the news:", never "because": being next
// to a move does not make it the cause. Headlines only: no article text, no summaries.
import type { NewsHeadline } from "@/lib/api";
import { fmtIsoDateTime } from "@/lib/freshness";

export const NEWS_LABEL = "In the news:";
export const MOVERS_TITLE = "Today's biggest movers";
export const MOVERS_SUBTITLE = "The S&P 500 stocks up and down the most today, from our latest stored quotes.";
export const STORIES_TITLE = "In the news";
export const STORIES_SUBTITLE = "Today's stories about S&P 500 companies, the companies that moved most first. Headlines link to the original article.";

export function fmtMovePct(pct: number): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/** The printed change's color, one rule for the mover rows and In the news: green up (or unchanged), red down. */
export function moveTone(pct: number): string {
  return pct >= 0 ? "text-success" : "text-destructive";
}

/** "Yahoo · Oct 8, 11:29 AM ET": where and when a headline was published. */
export function headlineByline(h: NewsHeadline): string {
  const when = fmtIsoDateTime(h.published_at);
  return [h.source, when].filter(Boolean).join(" \u00B7 ");
}
