import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Alert Interface",
  description: "Personal finance research tool — catalyst panel, watchlists, AI research.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <header className="border-b bg-background/95 backdrop-blur sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-8 h-13 flex items-center gap-6">
            <Link href="/" className="font-bold text-sm tracking-tight mr-2">
              Alert Interface
            </Link>
            <Link
              href="/build"
              className="text-sm font-semibold text-primary hover:text-primary/80 transition-colors"
            >
              Build a Trade
            </Link>
            <Link
              href="/theses"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Tracker
            </Link>
            <Link
              href="/watchlist"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Watchlists
            </Link>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
