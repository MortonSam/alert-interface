import type { MetadataRoute } from "next";

// The public pages and every active ticker page (read from the API at request time; a failed read lists the public pages alone).
// Per-visitor pages (My Trades, Watchlists) are left out.
export const SITE = "https://alertinterface.com";
export const PUBLIC_PATHS = ["/", "/discover", "/build", "/ivy", "/ivy/desk", "/ivy/trades", "/disclosures"];
export const revalidate = 3600;

export async function activeSymbols(apiBase: string | undefined, fetcher: typeof fetch = fetch): Promise<string[]> {
  if (!apiBase) return [];
  try {
    const res = await fetcher(apiBase + "/v1/tickers?active_only=true", { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const rows = (await res.json()) as { symbol: string }[];
    return rows.map((t) => t.symbol).filter(Boolean).sort();
  } catch {
    return [];
  }
}

export function sitemapEntries(symbols: string[], lastmod: Date): MetadataRoute.Sitemap {
  const pages = PUBLIC_PATHS.map((path) => ({ url: `${SITE}${path === "/" ? "" : path}`, lastModified: lastmod }));
  return pages.concat(symbols.map((s) => ({ url: `${SITE}/tickers/${encodeURIComponent(s)}`, lastModified: lastmod })));
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const symbols = await activeSymbols(process.env.NEXT_PUBLIC_API_URL);
  return sitemapEntries(symbols, new Date());
}
