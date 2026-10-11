import type { Metadata } from "next";
import Link from "next/link";
import { Bodoni_Moda, DM_Serif_Display, Gloock, Instrument_Serif, Libre_Caslon_Display, Newsreader, Source_Serif_4 } from "next/font/google";
import { HeroSearchButton } from "@/components/TickerSearch";
import { BRAND } from "@/lib/brand";

// A type study: the home page's opening screen with its headline set in seven candidate faces, each at its strongest
// available weight. Only the headline changes face; the subhead and buttons stay in the site's sans. Not linked from any page,
// not in the sitemap, and noindex.
export const metadata: Metadata = { title: "Type preview", robots: { index: false, follow: false } };

const instrument = Instrument_Serif({ subsets: ["latin"], weight: ["400"], display: "swap" });
const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: ["400"], display: "swap" });
const newsreader = Newsreader({ subsets: ["latin"], weight: ["800"], display: "swap" });
const caslon = Libre_Caslon_Display({ subsets: ["latin"], weight: ["400"], display: "swap" });
const gloock = Gloock({ subsets: ["latin"], weight: ["400"], display: "swap" });
const sourceSerif = Source_Serif_4({ subsets: ["latin"], weight: ["900"], display: "swap" });
const bodoni = Bodoni_Moda({ subsets: ["latin"], weight: ["900"], display: "swap" });

const FACES = [
  { name: "Instrument Serif", font: instrument, weight: 400 },
  { name: "DM Serif Display", font: dmSerif, weight: 400 },
  { name: "Newsreader", font: newsreader, weight: 800 },
  { name: "Libre Caslon Display", font: caslon, weight: 400 },
  { name: "Gloock", font: gloock, weight: 400 },
  { name: "Source Serif 4", font: sourceSerif, weight: 900 },
  { name: "Bodoni Moda", font: bodoni, weight: 900 },
];

export default function TypePreview() {
  return (
    <main className="pb-16">
      <style>{`
        .tp-h1 { font-size: clamp(26px, 7.4vw, 44px); line-height: 1.08; letter-spacing: -.02em; text-wrap: balance; }
        .tp-heron { width: min(58vw, 260px); height: auto; }
        @media (min-width: 1024px) {
          .tp-h1 { font-size: clamp(34px, min(3.5vw, 6.2svh), 66px); }
          .tp-heron { width: 100%; max-width: 760px; max-height: 70svh; object-fit: contain; }
        }
      `}</style>
      {FACES.map(({ name, font, weight }) => (
        <section key={name} className="border-t border-border sm:min-h-[calc(100svh-3.25rem-1px)] flex flex-col">
          <p className="font-mono text-xs text-primary px-4 sm:px-8 pt-6">{name} · {weight}</p>
          <div className="flex-1 grid items-center max-w-[88rem] w-full mx-auto px-4 sm:px-8 pt-8 pb-16 lg:py-0 gap-y-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-x-14">
            <div className="flex justify-start lg:justify-end">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={BRAND.heron} alt="" aria-hidden="true" className="tp-heron" />
            </div>
            <div className="text-left">
              <h1 className={`tp-h1 ${font.className} text-foreground`} style={{ fontWeight: weight }}>
                Trading apps teach you to tap. Pro tools assume you know.{" "}
                <span className="text-primary">Alert Interface teaches you what Wall Street knows.</span>
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
        </section>
      ))}
    </main>
  );
}
