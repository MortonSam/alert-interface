// Interim brand set (2026-10-10): every brand asset lives in public/brand and is referenced only through these paths, so the
// designer's final files replace them in one place. The lockup reference image in that folder is a visual guide only and is never shown.
// The market-data credit in the sitewide footer (an Intrinio Order Form condition, 2026-10-14): static copy, the same at every hour;
// it does not depend on market hours or on any data call. Rendered once, in app/layout.tsx, so every route carries it. The link is
// followed: rel is noopener only, never nofollow, ugc or sponsored (tested).
export const MARKET_DATA_CREDIT = { text: "Market data from Intrinio", href: "https://intrinio.com", rel: "noopener" } as const;

export const BRAND = {
  heron: "/brand/heron-transparent.svg",        // the header lockup: the site's background is always dark (html.dark)
  heronDark: "/brand/heron-dark.svg",           // the dark square version: icons and the share image are made from it
  ivyMark: "/brand/ivy-mark.svg",
  favicon: "/brand/favicon.ico",
  favicon16: "/brand/favicon-16.png",
  favicon32: "/brand/favicon-32.png",
  appleTouchIcon: "/brand/apple-touch-icon.png",
  manifest: "/brand/site.webmanifest",
  ogImage: "/brand/og.png",
} as const;
