import Link from "next/link";
import { TickerGrid } from "./ticker-grid";
import { ScrollReveal } from "@/components/ScrollReveal";
import { CountUp } from "@/components/CountUp";
import { IvyStatLine } from "@/components/IvyStatLine";
import { StoryFlow } from "@/components/StoryFlow";
import { HeroReveal } from "@/components/HeroReveal";

// ── Static sample data for the note preview ──────────────────────────────────

function NotePreview() {
  return (
    <div className="relative rounded-2xl border border-border bg-card">
      {/* Status line */}
      <div className="flex items-center gap-2 px-5 py-2.5 border-b border-border bg-secondary/40">
        <span className="h-2 w-2 rounded-full bg-success" />
        <span className="font-mono text-[11px] text-muted-foreground">
          Generated &amp; verified
        </span>
      </div>

      <div className="px-6 py-5 space-y-5">
        {/* Hero */}
        <div>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-display text-xl font-bold text-foreground leading-tight">
                AAPL
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                Apple Inc.
              </p>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold tracking-wide bg-cool/10 text-cool border-cool/25">
              <span className="text-[8px]">{"\u25CF"}</span>
              Neutral
            </span>
          </div>
          <p className="font-mono text-xs text-muted-foreground/70 mt-2">
            Information Technology {"\u00b7"} Technology Hardware {"\u00b7"} $4.30T
          </p>
        </div>

        {/* Stat strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 rounded-lg bg-secondary/50 px-4 py-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Market Cap</span>
            <span className="font-mono text-sm font-semibold text-foreground">$4.30T</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">EPS</span>
            <span className="font-mono text-sm font-semibold text-foreground">$2.01</span>
            <span className="text-[11px] text-success">vs $1.94 est {"\u00b7"} +3.6%</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Beat Streak</span>
            <span className="font-mono text-sm font-semibold text-foreground">18/20</span>
            <span className="text-[11px] text-muted-foreground">EPS beats</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Latest Move</span>
            <span className="font-mono text-sm font-semibold text-success">+3.56%</span>
            <span className="text-[11px] text-muted-foreground">post-earnings 1d {"\u00b7"} beat</span>
          </div>
        </div>

        {/* What They Do */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="h-2 w-2 rounded-full bg-cool" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-cool">
              What They Do
            </span>
          </div>
          <p className="text-[13px] text-foreground/85 leading-[1.65]">
            Apple designs, manufactures, and markets smartphones, personal computers,
            tablets, wearables, and accessories. Services (including the App Store,
            Apple Music, iCloud, and Apple Pay) now represent a growing share of revenue
            with higher margins than hardware.
          </p>
        </div>

        {/* Recent Highlights */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="h-2 w-2 rounded-full bg-success" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-success">
              Recent Highlights
            </span>
            <span className="text-[11px] text-muted-foreground/50">2 points</span>
          </div>
          <div className="flex flex-col gap-3">
            <div className="border-l-2 border-l-success/30 bg-success/[0.04] pl-3.5 py-1 rounded-r-md">
              <p className="text-[13px] font-semibold text-foreground leading-snug">
                Services revenue hit $26.3B
              </p>
              <p className="text-[13px] text-foreground/80 leading-[1.65] mt-0.5">
                Services grew 14% YoY and now carry a gross margin above 75%, providing a
                durable profit engine even if hardware cycles slow.
              </p>
            </div>
            <div className="border-l-2 border-l-success/30 bg-success/[0.04] pl-3.5 py-1 rounded-r-md">
              <p className="text-[13px] font-semibold text-foreground leading-snug">
                18 of 20 quarters beat
              </p>
              <p className="text-[13px] text-foreground/80 leading-[1.65] mt-0.5">
                The consistency of EPS beats suggests conservative guidance and reliable
                execution, though markets may already price in a beat.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Caption pill */}
      <div className="flex justify-center py-4 border-t border-border">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-4 py-1.5 text-[11px] font-mono text-muted-foreground">
          <span className="text-[8px] text-success">{"\u25CF"}</span>
          Sample note from Q2 2026
        </span>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function Home() {
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
          font-size: clamp(40px, 5.5vw, 84px);
          line-height: 1;
          letter-spacing: -.02em;
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
          <HeroReveal className="flex-1 flex flex-col items-center justify-center text-center max-w-7xl w-full mx-auto px-8">
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
              Every number explained, every claim checked before you see it.
            </p>

            <div data-hero-fade className="flex flex-wrap gap-[13px] justify-center mt-8">
              <a
                href="#market"
                className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity"
              >
                Browse the market ↓
              </a>
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

        {/* ── 2. Big three numbers ──────────────────────────────── */}
        <section className="min-h-[100svh] flex items-center justify-center px-8">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-16 md:gap-12 max-w-[1440px] w-full mx-auto text-center">
            {[
              { value: 10000, suffix: "+", label: "Earnings reports studied" },
              { value: 165000, suffix: "+", label: "Analyst actions since 2011" },
              { value: 100000, suffix: "+", label: "Option contracts priced daily" },
            ].map((stat) => (
              <div key={stat.label}>
                <CountUp
                  value={stat.value}
                  suffix={stat.suffix}
                  className="stat-number font-display font-bold text-foreground block whitespace-nowrap"
                />
                <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground mt-3">
                  {stat.label}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* ── 3. The Challenge ──────────────────────────────────── */}
        <section className="min-h-[100svh] flex items-center justify-center px-8">
          <div className="text-center">
            <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
              The challenge
            </p>
            <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
              Trading apps hand you confetti. Terminals cost thirty grand a year.
            </h2>
            <p className="text-sm text-muted-foreground mt-6 max-w-2xl mx-auto">
              Thirty million people started investing since 2020. Most of them
              research the way there&#39;s always been to research: Yahoo for the
              numbers, Reddit for opinions they can&#39;t trust, YouTube to learn
              what a P/E is, their broker for options they don&#39;t understand, and
              a chatbot that makes things up because nothing checks it.
            </p>
          </div>
        </section>

        {/* ── 4. The Solution ──────────────────────────────────── */}
        <section className="min-h-[100svh] flex items-center justify-center px-8">
          <div className="max-w-4xl w-full mx-auto">
            <div className="text-center">
              <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground mb-6">
                The solution
              </p>
              <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
                One workspace where every number comes with its meaning
                attached, and every claim is checked before you see it.
              </h2>
            </div>

            <div className="mt-12">
              <div className="border-t border-border pt-4 pb-5">
                <h3 className="font-display text-[15px] font-bold text-foreground">
                  Grounded in real data
                </h3>
                <p className="text-[13px] text-foreground/75 leading-[1.65] mt-1.5">
                  Every figure (earnings, margins, valuation) comes straight from filings
                  and market data. The AI writes the analysis; the numbers are exact.
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
                  A second model cross-checks every statement against the source filing
                  and flags anything it can&#39;t support. No confident hallucinations.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── 5. The Analyst ───────────────────────────────────── */}
        <section className="min-h-[100svh] flex items-center justify-center px-8">
          <div className="text-center">
            <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
              The analyst
            </p>
            <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
              Then Ivy makes the call, and keeps score in public.
            </h2>
            <p className="text-sm text-muted-foreground mt-6 max-w-lg mx-auto">
              Every pick she has ever made lives on a ledger she can&#39;t edit.
              Her losses sit right next to her wins.
            </p>

            <IvyStatLine className="font-mono text-xs text-muted-foreground mt-6" />

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
          <section className="max-w-3xl mx-auto px-8 py-24">
            <div className="text-center mb-12">
              <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
                See it in action
              </p>
              <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
                The note does the explaining
              </h2>
              <p className="text-sm text-muted-foreground mt-4 max-w-lg mx-auto">
                Earnings, financials, and risk analysis, with every number you can hover to understand.
              </p>
            </div>
            <NotePreview />
          </section>
        </ScrollReveal>

        {/* ── 7. Market grid ───────────────────────────────────── */}
        <ScrollReveal>
          <section id="market" className="max-w-7xl mx-auto px-8 py-24">
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
          <section className="max-w-4xl mx-auto px-8 py-24 text-center">
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
