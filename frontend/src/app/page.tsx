import Link from "next/link";
import LatestVerifiedNote from "@/components/LatestVerifiedNote";
import { HeroSearchButton } from "@/components/TickerSearch";
import { TickerGrid } from "./ticker-grid";
import { HomeLedgerBody, HomeLedgerFootnote, HomeLedgerHeadline } from "@/components/IvyCopy";
import { SiteCounters } from "@/components/SiteCounters";
import { fetchSiteStatsServer } from "@/lib/siteStats";
import { IvyStatLine } from "@/components/IvyStatLine";
import { IvyMark } from "@/components/IvyMark";
import { HomeSnap } from "@/components/HomeSnap";
import { BRAND } from "@/lib/brand";

// The counters are rendered on the server and revalidated: a backend that is slow, restarting or erroring never costs the
// page its first screen, because a failed revalidation keeps the last good render (lib/siteStats). Next needs this export as a
// literal; lib/siteStats.STATS_REVALIDATE_SECONDS carries the same number and a test holds them equal.
export const revalidate = 300;

export default async function Home() {
  const initial = await fetchSiteStatsServer();
  return (
    <main>
      {/* one section per screen: the browser's own scroll snap moves one section per gesture (components/HomeSnap) */}
      <HomeSnap />
      <style>{`
        .open-h1 {
          font-size: clamp(34px, 10.4vw, 76px);   /* "Wall Street sees." is about 8.6em wide: one line from a 390px phone up */
          white-space: nowrap;
          line-height: 1.02;
          letter-spacing: -.035em;
        }
        .open-heron { width: min(58vw, 260px); height: auto; }
        @media (min-width: 1024px) {
          .open-h1 { font-size: clamp(54px, 5.4vw, 84px); }
          .open-heron { width: 100%; max-width: 760px; max-height: 70svh; object-fit: contain; }
        }
        /* the entrance: the heron settles first, then the headline reveals, then the rest */
        @keyframes heron-settle { from { opacity: 0; transform: translateX(-28px) scale(.985); } to { opacity: 1; transform: none; } }
        @keyframes line-reveal  { from { opacity: 0; transform: translateY(.35em); clip-path: inset(0 0 100% 0); } to { opacity: 1; transform: none; clip-path: inset(0 0 0 0); } }
        @keyframes soft-in      { from { opacity: 0; } to { opacity: 1; } }
        .open-heron  { animation: heron-settle 1100ms cubic-bezier(.2,.7,.15,1) both; }
        .open-line   { animation: line-reveal 700ms cubic-bezier(.2,.7,.2,1) both; }
        .open-line-1 { animation-delay: 650ms; }
        .open-line-2 { animation-delay: 820ms; }
        .open-rest   { animation: soft-in 700ms ease-out 1150ms both; }
        .open-cue    { animation: soft-in 900ms ease-out 1700ms both; }
        @media (prefers-reduced-motion: reduce) {
          .open-heron, .open-line, .open-rest, .open-cue { animation: none; }
        }
        .stat-number {
          font-size: clamp(36px, 4.2vw, 60px);   /* lib/siteCounters.ts COUNTER_LAYOUT.font: seven characters fit a quarter column from 1024px up */
          line-height: 1;
          letter-spacing: -.02em;
          font-variant-numeric: tabular-nums;
        }
        .statement-h2 {
          font-size: clamp(32px, 6vw, 72px);
          line-height: 1.15;
          letter-spacing: -.025em;
        }
      `}</style>

      {/* ── 1. The opening: the heron large on the left facing the words, the headline, subhead and buttons on its right; on a
             phone the heron sits above the headline, left-aligned. Nothing else on the screen but a quiet scroll cue. ── */}
      <section className="snap-section relative flex flex-col bg-background">
        <div className="flex-1 grid items-center max-w-[88rem] w-full mx-auto px-4 sm:px-8 pt-8 pb-16 lg:py-0 gap-y-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-x-14">
          <div className="flex justify-start lg:justify-end">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={BRAND.heron} alt="" aria-hidden="true" className="open-heron" />
          </div>
          <div className="text-left">
            <h1 className="open-h1 font-display font-extrabold">
              <span className="open-line open-line-1 block text-foreground">Know what</span>
              <span className="open-line open-line-2 block text-primary">Wall Street sees.</span>
            </h1>
            <div className="open-rest">
              <p className="text-foreground/70 text-lg mt-6 max-w-[34em]">
                One workspace for the retail investor, starting with the S&amp;P 500. Every number explained.
              </p>
              <div className="flex flex-wrap gap-[13px] mt-8">
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

      {/* ── 2. The counts: four live numbers from stored tables, on their own screen. ── */}
      <section className="snap-section px-4 sm:px-6 py-12 sm:py-0 flex items-center justify-center">
        <SiteCounters initial={initial} />
      </section>

        {/* ── 3. The Challenge ── */}
        <section className="snap-section flex items-center justify-center px-4 sm:px-8 py-12 sm:py-0">
          <div className="text-center">
            <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
              The challenge
            </p>
            <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
              Trading apps hand you confetti. Terminals cost thirty grand a year.
            </h2>
            <p className="text-sm text-muted-foreground mt-6 max-w-2xl mx-auto">
              Most people research the way there&#39;s always been to research: Yahoo for the
              numbers, Reddit for opinions they can&#39;t trust, YouTube to learn
              what a P/E is, their broker for options they don&#39;t understand, and
              a chatbot that makes things up because nothing checks it.
            </p>
          </div>
        </section>

        {/* ── 4. The Solution ──────────────────────────────────── */}
        <section className="snap-section py-12 sm:py-0 flex items-center justify-center px-4 sm:px-8">
          <div className="max-w-4xl w-full mx-auto">
            <div className="text-center">
              <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground mb-6">
                The solution
              </p>
              <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
                Every number comes with its meaning attached.
              </h2>
            </div>

            <div className="mt-12">
              <div className="border-t border-border pt-4 pb-5">
                <h3 className="font-display text-[15px] font-bold text-foreground">
                  Grounded in real data
                </h3>
                <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                  Every figure (earnings, margins, valuation) comes from filings and
                  market data, not from the model. The AI writes the analysis around them.
                </p>
              </div>
              <div className="border-t border-border pt-4 pb-5">
                <h3 className="font-display text-[15px] font-bold text-foreground">
                  Explained as you read
                </h3>
                <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                  Jargon decoded in context. See what each metric means for that specific
                  company, not a generic textbook definition.
                </p>
              </div>
              <div className="border-t border-border pt-4 pb-5">
                <h3 className="font-display text-[15px] font-bold text-foreground">
                  Claims you can verify
                </h3>
                <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                  A second model checks every statement against the source filing and
                  marks each one supported, unsupported or contradicted. The marks are
                  shown with the note; the check reduces errors, it does not remove them.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── 5. The Analyst ───────────────────────────────────── */}
        <section className="snap-section py-12 sm:py-0 flex items-center justify-center px-4 sm:px-8">
          <div className="text-center">
            <IvyMark size={48} className="mb-5" />
            <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
              The analyst
            </p>
            <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
              <HomeLedgerHeadline />
            </h2>
            <p className="text-sm text-muted-foreground mt-6 max-w-lg mx-auto">
              <HomeLedgerBody />
            </p>

            <IvyStatLine className="font-mono text-xs text-muted-foreground mt-6" />
            <p className="text-[11px] text-muted-foreground/50 mt-2">
              <HomeLedgerFootnote />
            </p>

            <div className="mt-8">
              <Link
                href="/ivy"
                className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity inline-block"
              >
                Meet Ivy →
              </Link>
            </div>
          </div>
        </section>
      {/* ── 6. See it in action: the latest verified note (the component renders nothing when none is current) ── */}
      <LatestVerifiedNote className="snap-section flex flex-col justify-center" />

        {/* ── 7. Market grid ───────────────────────────────────── */}
          <section id="market" className="snap-section max-w-7xl mx-auto px-4 sm:px-8 py-12 sm:py-16">
            <div className="text-center mb-12">
              <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
                Start anywhere
              </p>
              <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
                Browse the market
              </h2>
              <p className="text-sm text-muted-foreground mt-4 max-w-lg mx-auto">
                Pick a ticker to read its research note, earnings history, and options data.
              </p>
            </div>
            <TickerGrid />
          </section>

        {/* ── 8. Closing CTA ───────────────────────────────────── */}
          <section className="snap-section flex flex-col items-center justify-center max-w-4xl mx-auto px-4 sm:px-8 py-12 text-center">
            <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
              The point
            </p>
            <p className="text-lg sm:text-xl text-foreground/70 max-w-[34ch] mx-auto mb-5">
              Robinhood teaches you to tap. Bloomberg assumes you know.
            </p>
            <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
              Know what Wall Street knows. See the proof.
            </h2>

            <div className="mt-10">
              <Link
                href="/discover"
                className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity inline-block"
              >
                What&#39;s worth a look →
              </Link>
            </div>

            <div className="flex justify-center gap-8 mt-6">
              <Link
                href="/build"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Build a trade →
              </Link>
              <Link
                href="/ivy"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Meet Ivy →
              </Link>
            </div>
          </section>
    </main>
  );
}
