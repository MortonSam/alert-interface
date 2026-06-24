import Link from "next/link";
import { TickerGrid } from "./ticker-grid";

// ── Static sample data for the note preview ──────────────────────────────────

function NotePreview() {
  return (
    <div className="relative rounded-2xl border border-border bg-card overflow-hidden">
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
            Information Technology {"\u00b7"} Technology Hardware {"\u00b7"} $4.3T
          </p>
        </div>

        {/* Stat strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 rounded-lg bg-secondary/50 px-4 py-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Market Cap</span>
            <span className="font-mono text-sm font-semibold text-foreground">$4.3T</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">EPS</span>
            <span className="font-mono text-sm font-semibold text-foreground">$2.01</span>
            <span className="text-[11px] text-success">vs 1.94e {"\u00b7"} +3.6%</span>
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
            tablets, wearables, and accessories. Services — including the App Store,
            Apple Music, iCloud, and Apple Pay — now represent a growing share of revenue
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
                execution — though markets may already price in a beat.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Fade-out overlay */}
      <div
        className="absolute bottom-0 left-0 right-0 h-32 pointer-events-none"
        style={{
          background: "linear-gradient(180deg, transparent 0%, hsl(var(--card)) 90%)",
        }}
      />

      {/* Floating caption pill */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card/90 backdrop-blur-sm px-4 py-1.5 text-[11px] font-mono text-muted-foreground">
          <span className="text-[8px] text-success">{"\u25CF"}</span>
          An actual research note — grounded, explained, verified
        </span>
      </div>
    </div>
  );
}

// ── Value prop card ──────────────────────────────────────────────────────────

function PropCard({
  accent,
  icon,
  title,
  body,
}: {
  accent: string;
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className={`rounded-xl border border-border bg-card/60 p-5 border-l-[3px] ${accent}`}>
      <div className="flex items-center gap-3 mb-3">
        <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-secondary text-muted-foreground">
          {icon}
        </div>
        <h3 className="font-display text-[15px] font-bold text-foreground">
          {title}
        </h3>
      </div>
      <p className="text-[13px] text-foreground/75 leading-[1.65]">
        {body}
      </p>
    </div>
  );
}

// ── Section heading ──────────────────────────────────────────────────────────

function SectionHeading({
  kicker,
  heading,
  sub,
}: {
  kicker: string;
  heading: string;
  sub: string;
}) {
  return (
    <div className="text-center mb-10">
      <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-2">
        {kicker}
      </p>
      <h2 className="font-display text-2xl sm:text-3xl font-bold text-foreground">
        {heading}
      </h2>
      <p className="text-sm text-muted-foreground mt-2 max-w-lg mx-auto">
        {sub}
      </p>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function Home() {
  return (
    <main>
      <style>{`
        .hero-bg {
          background-image: url(/hero-cosmos.jpg);
          background-size: contain;
          background-position: center;
          background-repeat: no-repeat;
          background-color: #070606;
        }
        .hero-scrim {
          background:
            radial-gradient(ellipse 720px 560px at 18% 32%, rgba(7,6,6,.62) 0%, rgba(7,6,6,.28) 55%, transparent 75%),
            linear-gradient(180deg, rgba(7,6,6,.3) 0%, transparent 14%, transparent 44%, rgba(10,10,11,.78) 80%, #0A0A0B 100%);
        }
        .hero-eyebrow {
          letter-spacing: .18em;
          text-shadow: 0 1px 12px rgba(0,0,0,.85);
        }
        .hero-h1 {
          font-size: clamp(38px, 7vw, 60px);
          line-height: 1.02;
          letter-spacing: -.025em;
          text-shadow: 0 2px 40px rgba(0,0,0,.95), 0 1px 4px rgba(0,0,0,.85);
        }
        .hero-lede {
          color: #E4DFDB;
          font-size: 18px;
          line-height: 1.55;
          text-shadow: 0 1px 18px rgba(0,0,0,.92);
          max-width: 30em;
        }
        @keyframes hero-bob {
          0%, 100% { transform: translateY(0); }
          50%       { transform: translateY(4px); }
        }
        .hero-scroll-cue {
          animation: hero-bob 2.4s ease-in-out infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          .hero-scroll-cue { animation: none; }
        }
      `}</style>

      {/* ── Hero ─────────────────────────────────────────────── */}
      <div className="relative w-full overflow-hidden bg-background aspect-[1375/768] max-h-[86vh]">
        <div className="hero-bg absolute inset-0" />
        <div className="hero-scrim absolute inset-0" />

        <div className="relative z-10 flex flex-col h-full max-w-7xl mx-auto px-8">
          <div className="max-w-[600px] pt-[7vh]">
            <p className="hero-eyebrow font-mono text-xs uppercase text-muted-foreground mb-[14px]">
              Equity research tool
            </p>

            <h1 className="hero-h1 font-display font-extrabold text-foreground">
              Stock research<br />
              <span className="text-primary">that verifies</span><br />
              itself.
            </h1>

            <div className="hero-lede mt-[18px] mb-[22px] space-y-[10px]">
              <p>
                Alert Interface brings S&amp;P 500 company research into one
                workspace for retail investors, covering the business,
                valuation, financial quality, risks, earnings history, trade
                context, watchlists, and much more.
              </p>
              <p>
                Every figure is linked to its source, and every AI-written
                claim is checked against the underlying data before you see it.
              </p>
            </div>

            <div className="flex flex-wrap gap-[13px] items-center">
              <a
                href="#market"
                className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity"
              >
                Browse the market ↓
              </a>
              <Link
                href="/build"
                className="bg-black/40 backdrop-blur-sm border border-white/30 text-white font-semibold rounded-xl px-6 py-3.5 text-sm hover:border-white transition-colors"
              >
                Build a trade →
              </Link>
            </div>
          </div>

          <p className="hero-scroll-cue mt-auto mb-[30px] font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground">
            scroll to explore ↓
          </p>
        </div>
      </div>

      {/* ── Value props ───────────────────────────────────────── */}
      <section className="max-w-7xl mx-auto px-8 py-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <PropCard
            accent="border-l-cool"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 3v18h18" />
                <path d="m7 16 4-8 4 5 5-6" />
              </svg>
            }
            title="Grounded in real data"
            body="Every figure — earnings, margins, valuation — comes straight from filings and market data. The AI writes the analysis; the numbers are exact."
          />
          <PropCard
            accent="border-l-violet"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            }
            title="Explained as you read"
            body="Jargon decoded in context. See what each metric means for that specific company, not a generic textbook definition."
          />
          <PropCard
            accent="border-l-success"
            icon={
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            }
            title="Claims you can verify"
            body="A second model cross-checks every statement against the source filing and flags anything it can't support. No confident hallucinations."
          />
        </div>
      </section>

      {/* ── Note preview ──────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-8 pb-20">
        <SectionHeading
          kicker="See it in action"
          heading="The note does the explaining"
          sub="Earnings, financials, and risk analysis — with every number you can hover to understand."
        />
        <NotePreview />
      </section>

      {/* ── Market grid ──────────────────────────────────────── */}
      <section id="market" className="max-w-7xl mx-auto px-8 pb-20">
        <SectionHeading
          kicker="Start anywhere"
          heading="Browse the market"
          sub="Pick a ticker to read its research note, earnings history, and options data."
        />
        <TickerGrid />
      </section>

      {/* ── Closing CTA ──────────────────────────────────────── */}
      <section className="max-w-7xl mx-auto px-8 pb-20">
        <div
          className="relative rounded-2xl border border-border overflow-hidden px-8 py-16 text-center"
          style={{
            background: "radial-gradient(ellipse at 50% 40%, hsla(29,100%,55%,.08) 0%, transparent 70%), hsl(var(--card))",
          }}
        >
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-foreground">
            Know what you&#39;re buying.
          </h2>
          <p className="text-sm text-muted-foreground mt-3 max-w-md mx-auto">
            Research first. Understand the company, the numbers, and the risk — then decide.
          </p>
          <div className="flex flex-wrap gap-[13px] justify-center mt-8">
            <Link
              href="/discover"
              className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity"
            >
              Discover what&#39;s worth a look →
            </Link>
            <Link
              href="/build"
              className="border border-border text-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:border-foreground/40 transition-colors"
            >
              Build a trade →
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
