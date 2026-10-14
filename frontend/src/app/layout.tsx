import type { Metadata } from "next";
import localFont from "next/font/local";
import Link from "next/link";
import NavLinks from "@/components/NavLinks";
import { HeaderTickerSearch } from "@/components/TickerSearch";
import PostHogProvider from "@/components/PostHogProvider";
import { BRAND, MARKET_DATA_CREDIT } from "@/lib/brand";
import "./globals.css";

// Every face is self-hosted from src/fonts (the Latin subsets, each with its OFL licence): no build or page load fetches from
// Google Fonts. Headings are Newsreader; body text, buttons and labels Schibsted Grotesk; data IBM Plex Mono; the wordmark
// Playfair Display.
const fontDisplay = localFont({ src: "../fonts/newsreader-latin.woff2", weight: "200 800", variable: "--font-display", display: "swap" });
const fontUi = localFont({ src: "../fonts/schibsted-grotesk-latin.woff2", weight: "400 900", variable: "--font-ui", display: "swap" });
const fontMono = localFont({
  src: [
    { path: "../fonts/ibm-plex-mono-400-latin.woff2", weight: "400" },
    { path: "../fonts/ibm-plex-mono-500-latin.woff2", weight: "500" },
    { path: "../fonts/ibm-plex-mono-600-latin.woff2", weight: "600" },
  ],
  variable: "--font-mono", display: "swap",
});
const fontBrand = localFont({ src: "../fonts/playfair-display-latin.woff2", weight: "400 900", variable: "--font-brand", display: "swap" });   // the wordmark only

export const metadata: Metadata = {
  metadataBase: new URL("https://alertinterface.com"),
  alternates: { canonical: "./" },                       // each page's own path, resolved against metadataBase
  title: "Alert Interface | Teaches you what Wall Street knows",
  description: "One workspace for the retail investor, starting with the S&P 500. Every number explained, by an AI analyst who shows her work.",
  icons: {
    icon: [{ url: BRAND.favicon, sizes: "any" }, { url: BRAND.favicon32, sizes: "32x32", type: "image/png" }, { url: BRAND.favicon16, sizes: "16x16", type: "image/png" }],
    apple: [{ url: BRAND.appleTouchIcon, sizes: "180x180" }],
  },
  manifest: BRAND.manifest,
  openGraph: { title: "Alert Interface | Teaches you what Wall Street knows", url: "./", images: [{ url: BRAND.ogImage, width: 1200, height: 630, alt: "Alert Interface" }] },
  twitter: { card: "summary_large_image", images: [BRAND.ogImage] },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${fontDisplay.variable} ${fontUi.variable} ${fontMono.variable} ${fontBrand.variable}`}>
      <body className="font-sans antialiased">
        <PostHogProvider>
          <header className="border-b bg-background/95 backdrop-blur sticky top-0 z-40">
            <div className="relative max-w-7xl mx-auto px-4 sm:px-8 min-h-[3.25rem] py-2 sm:py-0 flex flex-wrap items-center gap-x-3 gap-y-1 sm:gap-6">
              <Link href="/" className="tap flex items-center gap-2 sm:mr-2" data-testid="brand-lockup">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={BRAND.heron} alt="" aria-hidden="true" width={34} height={34} className="h-[34px] w-[34px] -my-1" />
                <span className="font-brand text-[19px] font-medium leading-none tracking-[-0.005em] text-[#F1F0E7]">Alert Interface</span>
              </Link>
              <NavLinks />
              <HeaderTickerSearch />
            </div>
          </header>
          {children}
          <footer className="text-[11px] text-muted-foreground/70 text-center py-6">
            Alert Interface is an educational research tool. Nothing here is investment advice. Options involve substantial risk.
            {" "}<Link href="/disclosures" className="tap underline hover:text-muted-foreground">Disclosures</Link>
            <span className="block mt-1" data-testid="market-data-credit">
              <a href={MARKET_DATA_CREDIT.href} rel={MARKET_DATA_CREDIT.rel} className="tap underline hover:text-muted-foreground">{MARKET_DATA_CREDIT.text}</a>
            </span>
          </footer>
        </PostHogProvider>
      </body>
    </html>
  );
}
