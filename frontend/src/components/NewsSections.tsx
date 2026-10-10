"use client";

// Discover's "Today's biggest movers" and "In the news" (backend services/news, behind DISCOVER_NEWS_ENABLED). The API fails closed:
// when the stories, the quote snapshot or the news step are not fresh it says visible: false and nothing renders.

import Link from "next/link";
import type { IvyLine, MoverItem, NewsHeadline, NewsSectionsResponse } from "@/lib/api";
import { IvyMark } from "@/components/IvyMark";
import { SectionKicker } from "@/components/SectionKicker";
import { fmtIsoDateTime } from "@/lib/freshness";
import {
  MOVERS_SUBTITLE, MOVERS_TITLE, STORIES_SUBTITLE, STORIES_TITLE, fmtMovePct, headlineByline, moreStoriesLabel, moveTone,
} from "@/lib/newsSections";

function ExternalHeadline({ url, headline }: { url: string; headline: string }) {
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="text-foreground/85 hover:text-primary underline-offset-2 hover:underline break-words">
      {headline}
    </a>
  );
}

/** A stock's printed change, the same in the mover rows and In the news (the figure the headline guard checks headlines against). */
function MoveChange({ pct }: { pct: number }) {
  return <span className={`font-mono text-xs font-semibold ${moveTone(pct)}`} data-testid="move-change">{fmtMovePct(pct)}</span>;
}

/** The source story under Ivy's sentence (smaller), or the row's headline alone when her sentence did not pass. */
function SourceLine({ h, more, small }: { h: NewsHeadline; more?: number; small: boolean }) {
  const extra = moreStoriesLabel(more);
  return (
    <p className={`${small ? "mt-1.5 text-xs" : "text-sm"} leading-snug min-w-0`}>
      <ExternalHeadline url={h.url} headline={h.headline} />
      <span className={`block ${small ? "text-[11px]" : "text-xs"} text-muted-foreground mt-0.5`}>
        {headlineByline(h)}{extra ? ` \u00B7 ${extra}` : ""}
      </span>
    </p>
  );
}

/** Ivy's sentence with her vine, then the story that informed her most; without a sentence, the headline display. */
function RowExplanation({ ivy, headline }: { ivy: IvyLine | null; headline: NewsHeadline | null }) {
  if (!ivy) return headline ? <div className="mt-0.5 sm:mt-0 min-w-0"><SourceLine h={headline} small={false} /></div> : null;
  const source = ivy.lead ?? (ivy.result === "no_news" ? null : headline);
  return (
    <div className="mt-1 sm:mt-0 min-w-0" data-testid="ivy-line">
      <p className="flex gap-2 text-sm leading-snug text-foreground">
        <IvyMark size={16} className="mt-[0.15em] shrink-0" />
        <span>{ivy.sentence}</span>
      </p>
      {source && <div className="pl-6"><SourceLine h={source} more={ivy.lead ? ivy.more : 0} small /></div>}
      {!source && ivy.result === "no_news" && headline && <div className="pl-6"><SourceLine h={headline} small /></div>}
    </div>
  );
}

function MoverRow({ m }: { m: MoverItem }) {
  return (
    <li className="py-3 sm:grid sm:grid-cols-[18rem_minmax(0,1fr)] sm:gap-x-6" data-testid="mover-row">
      <div className="flex items-baseline gap-2 min-w-0">
        <Link href={`/tickers/${m.symbol}`} className="tap font-display text-sm font-bold text-foreground hover:text-primary shrink-0">{m.symbol}</Link>
        {m.name && <span className="text-sm text-muted-foreground min-w-0 break-words">{m.name}</span>}
        <span className="ml-auto pl-2 font-mono text-xs text-right shrink-0">
          <span className="text-muted-foreground">${m.price.toFixed(2)}</span>{" "}
          <MoveChange pct={m.change_pct} />
          <span className="block text-[10px] text-muted-foreground/60 font-sans">as of {fmtIsoDateTime(m.quote_time)}</span>
        </span>
      </div>
      <RowExplanation ivy={m.ivy ?? null} headline={m.headline} />
    </li>
  );
}

/** Which of the two sections render: the page numbers its sections in order, so it asks before rendering any of them. */
export function newsSectionsShown(data: NewsSectionsResponse | null): { movers: boolean; stories: boolean } {
  if (!data || !data.visible) return { movers: false, stories: false };
  return { movers: data.up.length + data.down.length > 0, stories: data.stories.length > 0 };
}

export default function NewsSections({ data, indexes }: { data: NewsSectionsResponse | null; indexes: { movers?: string; stories?: string } }) {
  const shown = newsSectionsShown(data);
  if (!data || (!shown.movers && !shown.stories)) return null;
  const hasMovers = shown.movers;
  return (
    <>
      {hasMovers && (
        <section className="border-t border-border py-10" data-testid="news-movers">
          <SectionKicker index={indexes.movers ?? ""} label="Today" />
          <h2 className="font-display text-xl font-bold text-foreground">{MOVERS_TITLE}</h2>
          <p className="text-sm text-muted-foreground mt-1 mb-6">{MOVERS_SUBTITLE}</p>
          <div className="grid gap-x-10 gap-y-6 lg:grid-cols-2">
            {[{ title: "Up the most", rows: data.up }, { title: "Down the most", rows: data.down }].map((side) => (
              <div key={side.title}>
                <p className="font-mono text-[11px] uppercase tracking-[.14em] text-muted-foreground mb-1">{side.title}</p>
                <ul className="divide-y divide-border/60">{side.rows.map((m) => <MoverRow key={m.symbol} m={m} />)}</ul>
              </div>
            ))}
          </div>
        </section>
      )}
      {data.stories.length > 0 && (
        <section className="border-t border-border py-10" data-testid="news-stories">
          <SectionKicker index={indexes.stories ?? ""} label="Headlines" />
          <h2 className="font-display text-xl font-bold text-foreground">{STORIES_TITLE}</h2>
          <p className="text-sm text-muted-foreground mt-1 mb-6">{STORIES_SUBTITLE}</p>
          <ul className="divide-y divide-border/60">
            {data.stories.map((st) => (
              <li key={st.url} className="py-3 sm:grid sm:grid-cols-[6rem_minmax(0,1fr)] sm:gap-x-6" data-testid="news-story">
                <div className="flex items-baseline gap-2 sm:flex-col sm:gap-0">
                  <Link href={`/tickers/${st.symbol}`} className="tap font-display text-sm font-bold text-foreground hover:text-primary">{st.symbol}</Link>
                  <MoveChange pct={st.change_pct} />
                </div>
                <RowExplanation ivy={st.ivy ?? null} headline={st} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
