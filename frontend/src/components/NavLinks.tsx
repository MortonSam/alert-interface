"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/build", label: "Build a Trade" },
  { href: "/theses", label: "Tracker" },
  { href: "/watchlist", label: "Watchlists" },
];

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <>
      {links.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            className={
              active
                ? "text-sm font-semibold text-primary hover:text-primary/80 transition-colors"
                : "text-sm text-muted-foreground hover:text-foreground transition-colors"
            }
          >
            {label}
          </Link>
        );
      })}
    </>
  );
}
