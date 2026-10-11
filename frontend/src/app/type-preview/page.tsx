import type { Metadata } from "next";
import Link from "next/link";
import { Crimson_Pro, EB_Garamond, Gloock, Libre_Baskerville, Libre_Caslon_Display, Libre_Caslon_Text, Newsreader } from "next/font/google";
import { HeroSearchButton } from "@/components/TickerSearch";
import { BRAND } from "@/lib/brand";

// A type study: the home page's opening screen with its headline set in seven faces, each at the weight on its label. Only the headline changes face; the subhead and buttons stay in the site's sans. Not linked from any page,
// not in the sitemap, and noindex.
export const metadata: Metadata = { title: "Type preview", robots: { index: false, follow: false } };

const caslonDisplay = Libre_Caslon_Display({ subsets: ["latin"], weight: ["400"], display: "swap" });
const caslonText = Libre_Caslon_Text({ subsets: ["latin"], weight: ["700"], display: "swap" });
const garamond = EB_Garamond({ subsets: ["latin"], weight: ["700"], display: "swap" });
const crimson = Crimson_Pro({ subsets: ["latin"], display: "swap" });            // variable: 650 sits between the named weights
const baskerville = Libre_Baskerville({ subsets: ["latin"], weight: ["700"], display: "swap" });
const newsreader = Newsreader({ subsets: ["latin"], weight: ["600"], display: "swap" });
const gloock = Gloock({ subsets: ["latin"], weight: ["400"], display: "swap" });

// Libre Caslon Display first and Gloock last, as references
const FACES = [
  { name: "Libre Caslon Display", font: caslonDisplay, weight: 400 },
  { name: "Libre Caslon Text", font: caslonText, weight: 700 },
  { name: "EB Garamond", font: garamond, weight: 700 },
  { name: "Crimson Pro", font: crimson, weight: 650 },
  { name: "Libre Baskerville", font: baskerville, weight: 700 },
  { name: "Newsreader", font: newsreader, weight: 600 },
  { name: "Gloock", font: gloock, weight: 400 },
];

export default function TypePreview() {
  return (
    <main className="pb-16">
      <style>{`
        .tp-h1 { font-size: clamp(26px, 7.4vw, 44px); line-height: 1.02; letter-spacing: -.035em; text-wrap: balance; }   /* the home page's .open-h1 */
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
