import type { Metadata } from "next";
import Link from "next/link";
import { IBM_Plex_Sans, Instrument_Serif, Inter_Tight, Playfair_Display } from "next/font/google";
import { HeroSearchButton } from "@/components/TickerSearch";
import { BRAND } from "@/lib/brand";

// A type study for Sam: the home page's opening screen and The Challenge headline set in four candidate faces. Not linked from
// any page, not in the sitemap, and noindex.
export const metadata: Metadata = { title: "Type preview", robots: { index: false, follow: false } };

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["700"], display: "swap" });
const instrument = Instrument_Serif({ subsets: ["latin"], weight: ["400"], display: "swap" });
const interTight = Inter_Tight({ subsets: ["latin"], weight: ["400", "800"], display: "swap" });
const plex = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "700"], display: "swap" });

const FACES = [
  { name: "Playfair Display", font: playfair, weight: "font-bold" },
  { name: "Instrument Serif", font: instrument, weight: "font-normal" },
  { name: "Inter Tight", font: interTight, weight: "font-extrabold" },
  { name: "IBM Plex Sans", font: plex, weight: "font-bold" },
];

export default function TypePreview() {
  return (
    <main className="pb-16">
      <style>{`
        .tp-h1 { font-size: clamp(34px, 10.4vw, 76px); line-height: 1.02; letter-spacing: -.03em; white-space: nowrap; }
        .tp-heron { width: min(58vw, 260px); height: auto; }
        .tp-h2 { font-size: clamp(32px, 6vw, 72px); line-height: 1.15; letter-spacing: -.025em; }
        @media (min-width: 1024px) {
          .tp-h1 { font-size: clamp(54px, 5.4vw, 84px); }
          .tp-heron { width: 100%; max-width: 680px; max-height: 62svh; object-fit: contain; }
        }
      `}</style>
      {FACES.map(({ name, font, weight }) => (
        <section key={name} className={`${font.className} border-t border-border`}>
          <p className="font-mono text-xs text-primary px-4 sm:px-8 pt-6" style={{ fontFamily: "var(--font-mono)" }}>{name}</p>

          {/* the opening screen */}
          <div className="grid items-center max-w-[88rem] w-full mx-auto px-4 sm:px-8 py-10 lg:py-16 gap-y-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-x-14">
            <div className="flex justify-start lg:justify-end">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={BRAND.heron} alt="" aria-hidden="true" className="tp-heron" />
            </div>
            <div className="text-left">
              <h1 className={`tp-h1 ${weight}`}>
                <span className="block text-foreground">Know what</span>
                <span className="block text-primary">Wall Street sees.</span>
              </h1>
              <p className="text-foreground/70 text-lg mt-6 max-w-[34em]">
                One workspace for the retail investor, starting with the S&amp;P 500. Every number explained.
              </p>
              <div className="flex flex-wrap gap-[13px] mt-8">
                <HeroSearchButton className="bg-primary text-primary-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:opacity-90 transition-opacity" />
                <Link href="/build" className="border border-border text-foreground font-semibold rounded-xl px-6 py-3.5 text-sm hover:border-foreground/40 transition-colors">
                  Build a trade →
                </Link>
              </div>
            </div>
          </div>

          {/* The Challenge headline */}
          <div className="text-center px-4 sm:px-8 pb-14">
            <h2 className={`tp-h2 ${weight} text-foreground max-w-[20ch] mx-auto`}>
              Trading apps hand you confetti. Terminals cost thirty grand a year.
            </h2>
          </div>
        </section>
      ))}
    </main>
  );
}
