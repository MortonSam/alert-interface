"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/ivy", label: "Meet Ivy" },
  { href: "/ivy/picks", label: "Ivy's Picks" },
  { href: "/ivy/trades", label: "Ivy's Trades" },
];

export default function IvyLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="mx-auto max-w-4xl px-4">
      <nav className="flex gap-1 border-b pt-6 mb-6">
        {tabs.map(({ href, label }) => {
          const active = href === "/ivy"
            ? pathname === "/ivy"
            : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={
                active
                  ? "px-4 py-2 text-sm font-semibold text-foreground border-b-2 border-primary -mb-px"
                  : "px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors -mb-px border-b-2 border-transparent"
              }
            >
              {label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
