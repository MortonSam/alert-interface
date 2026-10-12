import type { Metadata } from "next";
import { tickerTitle } from "@/lib/pageTitles";

// The ticker page itself is a client component; this server layout gives each ticker its own title, canonical and og:url
// ("Tesla (TSLA) earnings, options and research | Alert Interface"), read from the company record.
export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
  const { symbol } = await params;
  const sym = decodeURIComponent(symbol).toUpperCase();
  let name: string | null = null;
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (base) {
    try {
      const res = await fetch(`${base}/v1/tickers/by-symbol/${encodeURIComponent(sym)}`, { next: { revalidate: 3600 } });
      if (res.ok) name = ((await res.json()) as { name?: string | null }).name ?? null;
    } catch { /* the title falls back to the symbol alone */ }
  }
  const title = tickerTitle(sym, name);
  const path = `/tickers/${encodeURIComponent(sym)}`;
  return { title, alternates: { canonical: path }, openGraph: { title, url: path } };
}

export default function TickerLayout({ children }: { children: React.ReactNode }) {
  return children;
}
