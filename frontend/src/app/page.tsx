import Link from "next/link";
import { TickerGrid } from "./ticker-grid";

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
            linear-gradient(90deg, rgba(7,6,6,.6) 0%, rgba(7,6,6,.3) 24%, rgba(7,6,6,.06) 48%, rgba(7,6,6,0) 64%),
            linear-gradient(180deg, rgba(7,6,6,.3) 0%, transparent 14%, transparent 44%, rgba(10,10,11,.78) 80%, #0A0A0B 100%);
        }
        .hero-eyebrow {
          letter-spacing: .18em;
          text-shadow: 0 1px 12px rgba(0,0,0,.85);
        }
        .hero-h1 {
          font-size: clamp(34px, 6vw, 50px);
          line-height: 1.02;
          letter-spacing: -.035em;
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
        {/* Background image — contain so the full image shows */}
        <div className="hero-bg absolute inset-0" />

        {/* Scrim: left-side vignette + bottom fade to background */}
        <div className="hero-scrim absolute inset-0" />

        {/* Content column — mirrors site container */}
        <div className="relative z-10 flex flex-col h-full max-w-7xl mx-auto px-8">
          {/* Push text block to bottom */}
          <div className="mt-auto max-w-[600px] pb-[30px]">

            {/* Eyebrow */}
            <p className="hero-eyebrow font-mono text-xs uppercase text-primary mb-[18px]">
              Personal equity research
            </p>

            {/* H1 */}
            <h1 className="hero-h1 font-display font-extrabold text-foreground">
              Research stocks.<br />
              Draft options.<br />
              <span className="text-primary">See the risk.</span>
            </h1>

            {/* Lede */}
            <p className="hero-lede mt-[22px] mb-[30px]">
              AI-drafted options ideas grounded in live prices, earnings history,
              and volatility — with the payoff and max loss drawn out before you
              place an order. Not financial advice.
            </p>

            {/* CTAs */}
            <div className="flex flex-wrap gap-[13px] items-center">
              <Link
                href="/build"
                className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity"
              >
                Build a trade →
              </Link>
              <a
                href="#market"
                className="bg-black/40 backdrop-blur-sm border border-white/30 text-white font-semibold rounded-xl px-6 py-3.5 text-sm hover:border-white transition-colors"
              >
                Browse the market ↓
              </a>
            </div>

            {/* Scroll cue */}
            <p className="hero-scroll-cue font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground mt-[36px]">
              scroll to explore ↓
            </p>
          </div>
        </div>
      </div>

      {/* ── Market grid ──────────────────────────────────────── */}
      <div id="market" className="max-w-7xl mx-auto px-8 pb-8">
        <TickerGrid />
      </div>
    </main>
  );
}
