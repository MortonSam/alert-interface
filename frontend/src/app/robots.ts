import type { MetadataRoute } from "next";

// Crawlers may read every public page; the preview and admin paths carry their own noindex and are kept out here too.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/preview", "/admin"] },
    sitemap: "https://alertinterface.com/sitemap.xml",
  };
}
