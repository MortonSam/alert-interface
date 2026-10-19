import Link from "next/link";
import LatestVerifiedNote from "@/components/LatestVerifiedNote";
import { HeroSearchButton } from "@/components/TickerSearch";
import { TickerGrid } from "./ticker-grid";
import { HomeLedgerBody, HomeLedgerFootnote, HomeLedgerHeadline } from "@/components/IvyCopy";
import { SiteCounters } from "@/components/SiteCounters";
import { fetchSiteStatsServer } from "@/lib/siteStats";
import { IvyStatLine } from "@/components/IvyStatLine";
import { IvyMark } from "@/components/IvyMark";
import { BRAND } from "@/lib/brand";

// The counters are rendered on the server and revalidated: a backend that is slow, restarting or erroring never costs the
// page its first screen, because a failed revalidation keeps the last good render (lib/siteStats). Next needs this export as a
// literal; lib/siteStats.STATS_REVALIDATE_SECONDS carries the same number and a test holds them equal.
export const revalidate = 300;

// one column, one left edge, for every section after the opening (DESIGN.md: one left alignment)
const HOME_COL = "w-full max-w-5xl mx-auto px-4 sm:px-8 text-left";

export default async function Home() {
  const initial = await fetchSiteStatsServer();
  return (
    <main>
      <style>{`
        .open-h1 {
          font-size: clamp(32px, 3.6vw, 52px);    /* the display size of the one type scale: three lines under the heron on a phone */
          text-wrap: balance;
          line-height: 1.1;
          letter-spacing: -.01em;
        }
        .open-heron { width: auto; height: min(17svh, 150px); }   /* on a phone, by the visible height: the headline and both buttons fit the opening screen */
        @media (min-width: 1024px) {
          .open-heron { width: 100%; height: auto; max-width: 760px; max-height: 70svh; object-fit: contain; }
        }
        /* the entrance: the heron settles first, then the headline reveals, then the rest */
        @keyframes heron-settle { from { opacity: 0; transform: translateX(-28px) scale(.985); } to { opacity: 1; transform: none; } }
        @keyframes line-reveal  { from { opacity: 0; transform: translateY(.35em); clip-path: inset(0 0 100% 0); } to { opacity: 1; transform: none; clip-path: inset(0 0 0 0); } }
        @keyframes soft-in      { from { opacity: 0; } to { opacity: 1; } }
        .open-heron  { animation: heron-settle 1100ms cubic-bezier(.2,.7,.15,1) both; }
        .open-line   { animation: line-reveal 800ms cubic-bezier(.2,.7,.2,1) 650ms both; }
        .open-rest   { animation: soft-in 700ms ease-out 1150ms both; }
        .open-cue    { animation: soft-in 900ms ease-out 1700ms both; }
        @media (prefers-reduced-motion: reduce) {
          .open-heron, .open-line, .open-rest, .open-cue { animation: none; }
        }
        .stat-number {
          font-size: clamp(36px, 4.2vw, 60px);   /* seven counter characters fit a quarter column from 1024px up */
          line-height: 1;
          letter-spacing: -.01em;
          font-variant-numeric: tabular-nums;
        }
        .home-label { font-family: var(--font-mono); font-size: 12px; text-transform: uppercase; letter-spacing: .16em; color: hsl(var(--muted-foreground)); margin-bottom: 24px; }
      `}</style>

      {/* ── 1. The opening: the heron large on the left facing the words, the headline, subhead and buttons on its right; on a
             phone the heron sits above the headline, left-aligned. Nothing else on the screen but a quiet scroll cue. ── */}
      <section className="screen-section relative flex flex-col bg-background">
        <div className="flex-1 grid content-center lg:items-center max-w-[88rem] w-full mx-auto px-4 sm:px-8 pt-4 pb-14 lg:py-0 gap-y-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-x-14">
          <div className="flex justify-start lg:justify-end">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={BRAND.heron} alt="" aria-hidden="true" className="open-heron" />
          </div>
          <div className="text-left">
            <h1 className="open-h1 open-line font-display font-semibold text-primary">
              Alert Interface teaches you what Wall Street knows.
            </h1>
            <div className="open-rest">
              <p className="text-foreground/70 text-lg mt-4 sm:mt-6 max-w-[34em]">
                One workspace for the retail investor, starting with the S&amp;P 500. Every number explained, by an AI analyst who shows her work.
              </p>
              <div className="flex flex-wrap gap-[13px] mt-6 sm:mt-8">
                <HeroSearchButton className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity" />
                <Link
                  href="/build"
                  className="border border-border text-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:border-foreground/40 transition-colors"
                >
                  Build a trade →
                </Link>
              </div>
            </div>
          </div>
        </div>
        <p className="open-cue absolute inset-x-0 bottom-0 text-center pb-6 sm:pb-8 font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground">
          scroll to explore ↓
        </p>
      </section>

      {/* Every section after the opening: one column on one left edge (HOME_COL), a label in the one label style (.home-label),
          the headline, then its text. Labels name every section, so none is left without one. */}

      {/* ── 2. The counts: four live numbers from stored tables, a 2 x 2 grid on a phone. ── */}
      <section className="screen-section flex items-center py-12 sm:py-0">
        <div className={HOME_COL}>
          <p className="home-label">By the numbers</p>
          <SiteCounters initial={initial} />
        </div>
      </section>

      {/* ── 3. The problem ── */}
      <section className="screen-section flex items-center py-12 sm:py-0">
        <div className={HOME_COL}>
          <p className="home-label">The problem</p>
          <h2 className="text-display font-display font-bold text-foreground max-w-[20ch]">
            Trading apps throw you confetti. Terminals hand you a $30,000 bill.
          </h2>
          <p className="text-sm text-muted-foreground mt-6 max-w-2xl">
            Most trading apps are built to keep you trading, with confetti for every order and a buy
            button on every screen. The terminals professionals use show you everything, but
            they&#39;re priced for firms and assume you already know how to read them. Everyone in
            between is left to piece it together on their own.
          </p>
        </div>
      </section>

      {/* ── 4. The Challenge ── */}
      <section className="screen-section flex items-center py-12 sm:py-0">
        <div className={HOME_COL}>
          <p className="home-label">The challenge</p>
          <h2 className="text-display font-display font-bold text-foreground max-w-[20ch]">
            Six tabs. No answers.
          </h2>
          <p className="text-sm text-muted-foreground mt-6 max-w-2xl">
            Most investors still research across six tabs, with Yahoo for the numbers, Reddit for
            opinions they can&#39;t trust, YouTube to learn what a P/E is, the news to find out why a
            stock moved, their broker for options they don&#39;t understand, and a chatbot that makes
            things up because nothing checks it. None of them talk to each other, and none of them
            check each other&#39;s work.
          </p>
        </div>
      </section>

      {/* ── 5. The Solution ── */}
      <section className="screen-section flex items-center py-12 sm:py-0">
        <div className={HOME_COL}>
          <p className="home-label">The solution</p>
          <h2 className="text-display font-display font-bold text-foreground max-w-[20ch]">
            Every number comes with its meaning attached.
          </h2>
          <div className="mt-12 max-w-3xl">
            <div className="border-t border-border pt-4 pb-5">
              <h3 className="font-display text-[15px] font-bold text-foreground">Grounded in real data</h3>
              <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                Every figure (earnings, margins, valuation) comes from filings and
                market data, not from the model. The AI writes the analysis around them.
              </p>
            </div>
            <div className="border-t border-border pt-4 pb-5">
              <h3 className="font-display text-[15px] font-bold text-foreground">Explained as you read</h3>
              <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                Jargon decoded in context. See what each metric means for that specific
                company, not a generic textbook definition.
              </p>
            </div>
            <div className="border-t border-border pt-4 pb-5">
              <h3 className="font-display text-[15px] font-bold text-foreground">Claims you can verify</h3>
              <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                A second model checks every statement against the source filing and
                marks each one supported, unsupported or contradicted. The marks are
                shown with the note; the check reduces errors, it does not remove them.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 6. The Analyst ── */}
      <section className="screen-section flex items-center py-12 sm:py-0">
        <div className={HOME_COL}>
          <IvyMark size={48} className="mb-5" />
          <p className="home-label">The analyst</p>
          <h2 className="text-display font-display font-bold text-foreground max-w-[20ch]">
            <HomeLedgerHeadline />
          </h2>
          <p className="text-sm text-muted-foreground mt-6 max-w-lg">
            <HomeLedgerBody />
          </p>
          <IvyStatLine className="font-mono text-xs text-muted-foreground mt-6" />
          <p className="text-[11px] text-muted-foreground/50 mt-2">
            <HomeLedgerFootnote />
          </p>
          <div className="mt-8">
            <Link href="/ivy" className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity inline-block">
              Meet Ivy →
            </Link>
          </div>
        </div>
      </section>

      {/* ── 7. See it in action: the latest verified note (the component renders nothing when none is current) ── */}
      <LatestVerifiedNote className="screen-section flex flex-col justify-center" />

      {/* ── 8. Market grid ── */}
      <section id="market" className="screen-section py-12 sm:py-16">
        <div className={HOME_COL + " max-w-7xl"}>
          <div className="mb-12">
            <p className="home-label">Start anywhere</p>
            <h2 className="text-display font-display font-bold text-foreground max-w-[20ch]">Browse the market</h2>
            <p className="text-sm text-muted-foreground mt-4 max-w-lg">
              Pick a ticker to read its research note, earnings history, and options data.
            </p>
          </div>
          <TickerGrid />
        </div>
      </section>

      {/* ── 9. Closing CTA ── */}
      <section className="screen-section flex items-center py-12">
        <div className={HOME_COL}>
          <p className="home-label">The point</p>
          <h2 className="text-display font-display font-bold text-foreground max-w-[20ch]">
            Know what Wall Street knows. See the proof.
          </h2>
          <div className="mt-10">
            <Link href="/discover" className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity inline-block">
              What&#39;s worth a look →
            </Link>
          </div>
          <div className="flex gap-8 mt-6">
            <Link href="/build" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Build a trade →</Link>
            <Link href="/ivy" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Meet Ivy →</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
