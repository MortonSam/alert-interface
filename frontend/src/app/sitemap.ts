import type { MetadataRoute } from "next";

// The public pages and every active ticker page (read from the API at request time; a failed read lists the public pages alone).
// Per-visitor pages (My Trades, Watchlists) are left out.
export const SITE = "https://alertinterface.com";
export const PUBLIC_PATHS = ["/", "/discover", "/build", "/ivy", "/disclosures"];
// Listed until the API serves /ivy-page (IVY_WALKTHROUGH_ENABLED on): with the walkthrough on, both send a visitor to /ivy.
export const OLD_IVY_PATHS = ["/ivy/desk", "/ivy/trades"];
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

/** Whether the walkthrough is on, by the API's own answer; a failed read counts as off, as it does for the pages (lib/useIvyMode). */
export async function walkthroughOn(apiBase: string | undefined, fetcher: typeof fetch = fetch, seconds = 3600): Promise<boolean> {
  if (!apiBase) return false;
  try {
    return (await fetcher(apiBase + "/v1/ivy-page", { next: { revalidate: seconds } })).ok;
  } catch {
    return false;
  }
}

export function publicPaths(walkthrough: boolean): string[] {
  return walkthrough ? PUBLIC_PATHS : PUBLIC_PATHS.flatMap((p) => (p === "/ivy" ? [p, ...OLD_IVY_PATHS] : [p]));
}

export function sitemapEntries(symbols: string[], lastmod: Date, walkthrough = true): MetadataRoute.Sitemap {
  const pages = publicPaths(walkthrough).map((path) => ({ url: `${SITE}${path === "/" ? "" : path}`, lastModified: lastmod }));
  return pages.concat(symbols.map((s) => ({ url: `${SITE}/tickers/${encodeURIComponent(s)}`, lastModified: lastmod })));
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const api = process.env.NEXT_PUBLIC_API_URL;
  const [symbols, walkthrough] = await Promise.all([activeSymbols(api), walkthroughOn(api)]);
  return sitemapEntries(symbols, new Date(), walkthrough);
}
