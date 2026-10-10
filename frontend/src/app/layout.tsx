import type { Metadata } from "next";
import { Bricolage_Grotesque, Playfair_Display, Schibsted_Grotesk, IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";
import NavLinks from "@/components/NavLinks";
import { HeaderTickerSearch } from "@/components/TickerSearch";
import PostHogProvider from "@/components/PostHogProvider";
import { BRAND } from "@/lib/brand";
import "./globals.css";

const fontDisplay = Bricolage_Grotesque({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-display", display: "swap" });
const fontUi = Schibsted_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-ui", display: "swap" });
const fontMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap" });
const fontBrand = Playfair_Display({ subsets: ["latin"], weight: ["500"], variable: "--font-brand", display: "swap" });   // the wordmark only

export const metadata: Metadata = {
  title: "Alert Interface",
  description: "Personal finance research tool: catalyst panel, watchlists, Ivy-powered research.",
  icons: {
    icon: [{ url: BRAND.favicon, sizes: "any" }, { url: BRAND.favicon32, sizes: "32x32", type: "image/png" }, { url: BRAND.favicon16, sizes: "16x16", type: "image/png" }],
    apple: [{ url: BRAND.appleTouchIcon, sizes: "180x180" }],
  },
  manifest: BRAND.manifest,
  openGraph: { title: "Alert Interface", images: [{ url: BRAND.ogImage, width: 1200, height: 630, alt: "Alert Interface" }] },
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
          </footer>
        </PostHogProvider>
      </body>
    </html>
  );
}
