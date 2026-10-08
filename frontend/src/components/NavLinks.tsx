"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export const NAV_LINKS = [
  { href: "/discover", label: "Discover" },
  { href: "/build", label: "Build a Trade" },
  { href: "/ivy", label: "Ivy" },
  { href: "/theses", label: "My Trades" },
  { href: "/watchlist", label: "Watchlists" },
];

/** From 640px up the five links sit in the header row; below it a menu button opens them, so the header stays one row on a phone. */
export default function NavLinks() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent | TouchEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("touchstart", onDown); };
  }, [open]);

  const links = (onPhone: boolean) => NAV_LINKS.map(({ href, label }) => {
    const active = pathname === href || pathname.startsWith(href + "/");
    const tone = active ? "font-semibold text-primary hover:text-primary/80" : "text-muted-foreground hover:text-foreground";
    return (
      <Link key={href} href={href} className={`text-sm ${tone} transition-colors ${onPhone ? "block px-4 py-3" : ""}`}>
        {label}
      </Link>
    );
  });

  return (
    <>
      <div className="hidden sm:contents">{links(false)}</div>
      <div ref={ref} className="sm:hidden" data-testid="phone-menu">
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground"
        >
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
          </svg>
        </button>
        {open && (
          <nav className="absolute left-0 right-0 top-full border-b border-border bg-background shadow-lg divide-y divide-border/60">
            {links(true)}
          </nav>
        )}
      </div>
    </>
  );
}
