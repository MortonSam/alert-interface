import Link from "next/link";
import LatestVerifiedNote from "@/components/LatestVerifiedNote";
import { HeroSearchButton } from "@/components/TickerSearch";
import { TickerGrid } from "./ticker-grid";
import { ScrollReveal } from "@/components/ScrollReveal";
import { HomeLedgerBody, HomeLedgerFootnote, HomeLedgerHeadline } from "@/components/IvyCopy";
import { SiteCounters } from "@/components/SiteCounters";
import { fetchSiteStatsServer, STATS_REVALIDATE_SECONDS } from "@/lib/siteStats";
import { IvyStatLine } from "@/components/IvyStatLine";
import { StoryFlow } from "@/components/StoryFlow";
import { HeroReveal } from "@/components/HeroReveal";

// The counters are rendered on the server and revalidated: a backend that is slow, restarting or erroring never costs the
// page its first screen, because a failed revalidation keeps the last good render (lib/siteStats).
export const revalidate = STATS_REVALIDATE_SECONDS;

export default async function Home() {
  const initial = await fetchSiteStatsServer();
  return (
    <main>
      <style>{`
        @keyframes hero-bob {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(4px); }
        }
        .hero-scroll-cue {
          animation: hero-bob 2.4s ease-in-out infinite;
          animation-delay: 1.4s;
        }

        .hero-h1 {
          font-size: clamp(40px, 10vw, 120px);
          line-height: 1.05;
          letter-spacing: -.03em;
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

        @media (prefers-reduced-motion: reduce) {
          .hero-scroll-cue { animation: none; }
        }
      `}</style>

      <StoryFlow>
        {/* ── 1. Hero ────────────────────────────────────────────── */}
        <section className="min-h-[100svh] flex flex-col bg-background">
          <HeroReveal className="flex-1 flex flex-col items-center justify-center text-center max-w-7xl w-full mx-auto px-4 sm:px-8">
            <h1 className="hero-h1 font-display font-extrabold uppercase">
              <span data-hero-line className="block text-foreground">
                Stock research
              </span>
              <span data-hero-line className="block text-primary">
                that verifies
              </span>
              <span data-hero-line className="block text-foreground">
                itself.
              </span>
            </h1>

            <p data-hero-fade className="text-foreground/70 text-lg mt-6 max-w-[42em]">
              One workspace for the retail investor, starting with the S&amp;P 500.
              Every number explained; every claim checked, and the unsupported ones shown as unsupported.
            </p>

            <div data-hero-fade className="flex flex-wrap gap-[13px] justify-center mt-8">
              <HeroSearchButton className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity" />
              <Link
                href="/build"
                className="border border-border text-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:border-foreground/40 transition-colors"
              >
                Build a trade →
              </Link>
            </div>
          </HeroReveal>

          <p className="hero-scroll-cue text-center pb-8 font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground">
            scroll to explore ↓
          </p>
        </section>

        {/* ── 2. The counts: four live numbers from stored tables, the first thing under the hero. From 640px up the section is
               one screen (the viewport minus the sticky header, in svh) with the row centered and nothing else on it; below
               that it is a normal section. ── */}
        <section className="px-4 sm:px-6 py-20 sm:py-0 sm:min-h-[calc(100svh-3.25rem-1px)] sm:flex sm:items-center sm:justify-center">
          <SiteCounters initial={initial} />
        </section>

        {/* ── 3. The Challenge ──────────────────────────────────── */}
        <section className="flex items-center justify-center px-4 sm:px-8 py-24">
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
        <section className="min-h-[100svh] flex items-center justify-center px-4 sm:px-8">
          <div className="max-w-4xl w-full mx-auto">
            <div className="text-center">
              <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground mb-6">
                The solution
              </p>
              <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
                One workspace where every number comes with its meaning
                attached, and every claim is checked, with unsupported ones shown as unsupported.
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
        <section className="min-h-[100svh] flex items-center justify-center px-4 sm:px-8">
          <div className="text-center">
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
      </StoryFlow>

      {/* ── Free-scroll zone ───────────────────────────────────── */}
      <div>
        {/* ── 6. Note preview ──────────────────────────────────── */}
        <ScrollReveal>
          <section className="max-w-3xl mx-auto px-4 sm:px-8 py-24">
            <div className="text-center mb-12">
              <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
                See it in action
              </p>
              <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
                The latest verified note
              </h2>
              <p className="text-sm text-muted-foreground mt-4 max-w-lg mx-auto">
                Rendered from the stored note: its own figures, its own words, and what the second model found.
              </p>
            </div>
            <LatestVerifiedNote />
          </section>
        </ScrollReveal>

        {/* ── 7. Market grid ───────────────────────────────────── */}
        <ScrollReveal>
          <section id="market" className="max-w-7xl mx-auto px-4 sm:px-8 py-24">
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
        </ScrollReveal>

        {/* ── 8. Closing CTA ───────────────────────────────────── */}
        <ScrollReveal>
          <section className="max-w-4xl mx-auto px-4 sm:px-8 py-24 text-center">
            <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
              The point
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
        </ScrollReveal>
      </div>
    </main>
  );
}
