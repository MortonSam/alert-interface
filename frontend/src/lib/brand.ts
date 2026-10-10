// Interim brand set (2026-10-10): every brand asset lives in public/brand and is referenced only through these paths, so the
// designer's final files replace them in one place. The lockup reference image in that folder is a visual guide only and is never shown.
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
