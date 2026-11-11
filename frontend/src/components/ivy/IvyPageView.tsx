"use client";

// The one Ivy page as a demonstration (Sam, 2026-11-03): it shows her work rather than describing it, at the home page's pace, one
// screen per section with its content centered and one focal point each. 1. the headline and the search that starts a walkthrough;
// 2. a real step (NVIDIA's margins), rendered by the walkthrough's own StepScreen; 3. a real note sentence beside the filing passage
// that confirmed it, with the live count of checked statements; 4. the seven ideas, each linked to its example step; 5. the closing
// line. Every line is lib/ivyPageCopy's; the step, the example, the counts and the ideas come from the API, which answers only while
// IVY_WALKTHROUGH_ENABLED is on; until then app/ivy shows Meet Ivy as it was and never this page (lib/useIvyMode; Sam, 2026-11-10).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { StepScreen } from "@/components/walkthrough/Walkthrough";
import { api, type Ticker } from "@/lib/api";
import { fmtDate } from "@/lib/dates";
import { IVY_PAGE as C } from "@/lib/ivyPageCopy";
import { matchTickers } from "@/lib/tickerSearch";
import { readIvyPage } from "@/lib/useIvyMode";
import { fetchWalkthrough, type IvyPage, type Walkthrough } from "@/lib/walkthrough";

const walkHref = (symbol: string, step = 1) => `/tickers/${symbol}?learn=${step}`;
const EXAMPLE = { symbol: "NVDA", step: "margins" } as const;        // the step shown in section 2 (Sam, 2026-11-03)

function Screen({ children, testid }: { children: React.ReactNode; testid: string }) {
  return (
    <section className="screen-section flex flex-col items-center justify-center px-4 sm:px-8 py-12" data-testid={testid}>
      {children}
    </section>
  );
}

function WalkSearch({ page }: { page: IvyPage | null }) {
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
    <div className="mt-12 w-full max-w-2xl" data-testid="ivy-walk-search">
      <label htmlFor="ivy-walk-search" className="sr-only">{C.searchLabel}</label>
      <div className="relative">
        <input id="ivy-walk-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={C.searchPlaceholder} autoComplete="off"
          className="w-full rounded-2xl border-2 border-primary bg-background px-6 py-5 text-lg sm:text-xl text-foreground outline-none placeholder:text-muted-foreground focus:ring-4 focus:ring-primary/20" />
        {matches.length > 0 && (
          <ul className="absolute inset-x-0 top-full z-10 mt-2 rounded-xl border border-border bg-background text-left shadow-xl divide-y divide-border/60">
            {matches.map((t) => (
              <li key={t.symbol}>
                <button type="button" onClick={() => void open(t)} className="tap w-full px-5 py-3 text-left text-base hover:bg-muted">
                  <span className="font-semibold">{t.symbol}</span> <span className="text-muted-foreground">{t.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {missing && <p className="mt-3 text-sm text-muted-foreground">{missing}</p>}
      {/* the row holds its line before the picks are in, so the headline above never moves when they arrive */}
      <p className="mt-5 min-h-[1.25rem] flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
        {page && page.quick_picks.length > 0 && (
          <>
            <span>{C.quickPicks}</span>
            {page.quick_picks.map((q) => (
              <Link key={q.symbol} href={walkHref(q.symbol)} data-testid="ivy-quick-pick" className="tap font-semibold text-primary hover:text-foreground transition-colors">
                {q.symbol}
              </Link>
            ))}
          </>
        )}
      </p>
    </div>
  );
}

export default function IvyPageView() {
  const [page, setPage] = useState<IvyPage | null>(null);
  const [walk, setWalk] = useState<Walkthrough | null>(null);
  useEffect(() => {
    readIvyPage().then(setPage);
    fetchWalkthrough(EXAMPLE.symbol).then(setWalk);
  }, []);
  const step = walk?.steps.find((s) => s.key === EXAMPLE.step && s.status !== "absent") ?? null;
  const checkedOn = fmtDate(page?.trust.checked.as_of);
  const filed = fmtDate(page?.check?.filed);

  return (
    <main>
      <Screen testid="ivy-open">
        <h1 className="text-display font-display font-bold text-foreground max-w-[22ch] text-center">{C.headline}</h1>
        <WalkSearch page={page} />
      </Screen>

      {walk && step && (
        <Screen testid="ivy-step">
          <div className="w-full max-w-2xl">
            <p className="mb-6 font-mono text-xs uppercase tracking-[.16em] text-primary">{C.stepFrom(walk.name)}</p>
            <StepScreen step={step} w={walk} learned={{}} others={{}} preview />
            <div className="mt-8 text-center">
              <Link href={walkHref(walk.symbol)} className="inline-block rounded-xl bg-primary px-6 py-3.5 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity">
                {C.startWalk(walk.name)} →
              </Link>
            </div>
          </div>
        </Screen>
      )}

      {page?.check && (
        <Screen testid="ivy-check">
          <div className="w-full max-w-4xl">
            <h2 className="text-headline font-display font-semibold text-foreground text-center">{C.checkTitle}</h2>
            <div className="mt-10 grid grid-cols-1 gap-10 md:grid-cols-2 md:gap-14">
              <figure>
                <figcaption className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground">{C.noteFrom(page.check.name)}</figcaption>
                <blockquote className="mt-3 font-display text-xl leading-relaxed text-foreground">{page.check.sentence}</blockquote>
              </figure>
              <figure>
                <figcaption className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground">
                  {page.check.form && filed ? C.filingFrom(page.check.form, filed) : C.readFiling}
                </figcaption>
                <blockquote className="mt-3 border-l-2 border-primary/60 pl-4 font-display text-xl leading-relaxed text-foreground/90">
                  “{page.check.passage}”
                </blockquote>
                <a href={page.check.url} target="_blank" rel="noopener noreferrer" className="tap mt-3 inline-block text-sm text-cool hover:text-foreground">{C.readFiling} →</a>
              </figure>
            </div>
            {checkedOn && (
              <p className="mt-12 text-center text-sm text-muted-foreground" data-testid="ivy-checked">
                {C.checked(page.trust.checked.count.toLocaleString("en-US"), checkedOn)}
              </p>
            )}
          </div>
        </Screen>
      )}

      {page && page.ideas.length > 0 && (
        <Screen testid="ivy-ideas">
          <div className="w-full max-w-xl">
            <h2 className="text-headline font-display font-semibold text-foreground text-center">{C.ideasTitle}</h2>
            <ol className="mt-8 space-y-3 text-lg">
              {page.ideas.map((idea) => (
                <li key={idea.n} className="flex gap-4">
                  <span className="w-6 shrink-0 text-right font-mono text-muted-foreground">{idea.n}</span>
                  <Link href={walkHref(idea.symbol, idea.n)} className="tap text-foreground hover:text-primary transition-colors">{idea.title}</Link>
                </li>
              ))}
            </ol>
          </div>
        </Screen>
      )}

      <Screen testid="ivy-closing">
        <p className="statement-h2 font-display font-bold text-foreground max-w-[22ch] text-center">{C.closing}</p>
      </Screen>
    </main>
  );
}
