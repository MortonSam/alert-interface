import type { Metadata } from "next";
import { Bricolage_Grotesque, Schibsted_Grotesk, IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";
import NavLinks from "@/components/NavLinks";
import "./globals.css";

const fontDisplay = Bricolage_Grotesque({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-display", display: "swap" });
const fontUi = Schibsted_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-ui", display: "swap" });
const fontMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Alert Interface",
  description: "Personal finance research tool — catalyst panel, watchlists, AI research.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${fontDisplay.variable} ${fontUi.variable} ${fontMono.variable}`}>
      <body className="font-sans antialiased">
        <header className="border-b bg-background/95 backdrop-blur sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-8 h-13 flex items-center gap-6">
            <Link href="/" className="font-bold text-sm tracking-tight mr-2">
              Alert Interface
            </Link>
            <NavLinks />
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
