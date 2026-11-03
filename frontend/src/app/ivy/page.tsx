"use client";

// The one Ivy page (Sam, 2026-11-02): what Ivy does and why to trust her, and nothing of the old pick pages. Every line is
// lib/ivyPageCopy's; the quick picks, the seven ideas (each linked to the step it is shown on) and the counts with their dates come
// from GET /ivy-page, which answers only while IVY_WALKTHROUGH_ENABLED is on (the search, ideas and counts hide without it).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, type Ticker } from "@/lib/api";
import { fmtDate } from "@/lib/dates";
import { IVY_PAGE as C } from "@/lib/ivyPageCopy";
import { matchTickers } from "@/lib/tickerSearch";
import { fetchIvyPage, fetchWalkthrough, type IvyCount, type IvyPage } from "@/lib/walkthrough";

const walkHref = (symbol: string, step = 1) => `/tickers/${symbol}?learn=${step}`;

function WalkSearch({ page }: { page: IvyPage }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [missing, setMissing] = useState<string | null>(null);
  useEffect(() => {
    if (!query || tickers.length) return;
    api.tickers.list().then((t) => setTickers(t.filter((x) => x.index_member))).catch(() => {});
  }, [query, tickers.length]);
  const matches = useMemo(() => matchTickers(tickers, query, 6), [tickers, query]);

  async function open(t: { symbol: string; name: string | null }) {
    setQuery("");
    setMissing(null);
    const w = await fetchWalkthrough(t.symbol);
    if (w?.entry) router.push(walkHref(t.symbol));
    else setMissing(C.noWalkthrough(t.name || t.symbol));
  }

  return (
    <div className="mx-auto mt-10 w-full max-w-xl text-left" data-testid="ivy-walk-search">
      <label htmlFor="ivy-walk-search" className="block text-sm font-semibold text-foreground">{C.searchLabel}</label>
      <p className="mt-0.5 text-xs text-muted-foreground">{C.length(page.minutes)}</p>
      <input id="ivy-walk-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={C.searchPlaceholder} autoComplete="off"
        className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-foreground/40" />
      {matches.length > 0 && (
        <ul className="mt-1 rounded-lg border border-border divide-y divide-border/60">
          {matches.map((t) => (
            <li key={t.symbol}>
              <button type="button" onClick={() => void open(t)} className="tap w-full px-3 py-2 text-left text-sm hover:bg-muted">
                <span className="font-semibold">{t.symbol}</span> <span className="text-muted-foreground">{t.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {missing && <p className="mt-2 text-sm text-muted-foreground">{missing}</p>}
      {page.quick_picks.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{C.quickPicks}</span>
          {page.quick_picks.map((q) => (
            <Link key={q.symbol} href={walkHref(q.symbol)} data-testid="ivy-quick-pick"
              className="tap rounded-full border border-border px-3.5 py-1.5 text-sm text-foreground/85 hover:border-foreground/30">
              {q.symbol} <span className="text-muted-foreground">{q.name}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function TrustLine({ text, c }: { text: (n: string) => string; c: IvyCount }) {
  const date = fmtDate(c.as_of);
  return (
    <li className="rounded-lg border border-border/60 px-5 py-4">
      <p className="text-sm text-foreground">{text(c.count.toLocaleString("en-US"))}</p>
      {date && <p className="mt-1 text-xs text-muted-foreground">{C.asOf(date)}</p>}
    </li>
  );
}

export default function IvyPageView() {
  const [page, setPage] = useState<IvyPage | null>(null);
  useEffect(() => { fetchIvyPage().then(setPage); }, []);

  return (
    <main className="pb-20">
      <section className="pt-6 text-center">
        <h1 className="text-display font-display font-bold text-foreground max-w-[22ch] mx-auto">{C.headline}</h1>
        {page && <WalkSearch page={page} />}
      </section>

      <section className="mt-16 grid grid-cols-1 gap-4 md:grid-cols-3" data-testid="ivy-cards">
        {C.cards.map((card) => (
          <div key={card.key} className="rounded-lg border border-border/60 px-5 py-5">
            <h3 className="text-base font-semibold text-foreground">{card.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{card.body}</p>
          </div>
        ))}
      </section>

      {page && (
        <section className="mt-16" data-testid="ivy-trust">
          <h2 className="text-headline font-display font-semibold text-foreground">{C.trustTitle}</h2>
          <ul className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            <TrustLine text={C.trust.notes} c={page.trust.notes} />
            <TrustLine text={C.trust.confirmed} c={page.trust.confirmed} />
            <TrustLine text={C.trust.walkthroughs} c={page.trust.walkthroughs} />
          </ul>
        </section>
      )}

      {page && page.ideas.length > 0 && (
        <section className="mt-16" data-testid="ivy-ideas">
          <h2 className="text-headline font-display font-semibold text-foreground">{C.ideasTitle}</h2>
          <ol className="mt-4 space-y-3">
            {page.ideas.map((idea) => (
              <li key={idea.n} className="rounded-lg border border-border/60 px-5 py-4">
                <p className="text-sm font-semibold text-foreground">{idea.n}. {idea.title}</p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{idea.text}</p>
                <Link href={walkHref(idea.symbol, idea.n)} className="mt-2 inline-block text-sm font-medium text-primary hover:text-foreground transition-colors">
                  {C.ideaLink(idea.name)} →
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}

      <p className="mt-16 text-center text-base font-medium text-foreground" data-testid="ivy-closing">{C.closing}</p>
    </main>
  );
}
