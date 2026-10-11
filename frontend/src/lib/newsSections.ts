// Discover's news sections: the words they print. Each row leads with Ivy's one checked sentence (backend services/ivy_moves) and,
// under it, the story that informed her most; a row whose sentence did not pass shows its headline alone. Headlines only: no
// article text.
import type { NewsHeadline } from "@/lib/api";
import { fmtIsoDateTime } from "@/lib/freshness";

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

/** "and 2 more" when more than one story informed Ivy's sentence; null otherwise. */
export function moreStoriesLabel(more: number | null | undefined): string | null {
  return more && more > 0 ? `and ${more} more` : null;
}

/** "Yahoo · Oct 8, 11:29 AM ET": where and when a headline was published. */
export function headlineByline(h: NewsHeadline): string {
  const when = fmtIsoDateTime(h.published_at);
  return [h.source, when].filter(Boolean).join(" \u00B7 ");
}
