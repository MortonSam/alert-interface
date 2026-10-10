import type { MetadataRoute } from "next";

// The public pages. Per-visitor pages (My Trades, Watchlists) and per-ticker pages are left out.
const SITE = "https://alertinterface.com";
const PUBLIC_PATHS = ["/", "/discover", "/build", "/ivy", "/ivy/desk", "/ivy/trades", "/disclosures"];

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_PATHS.map((path) => ({ url: `${SITE}${path === "/" ? "" : path}` }));
}
