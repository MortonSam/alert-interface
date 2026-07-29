"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type HealthStatus } from "@/lib/api";

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

const tabs = [
  { href: "/ivy", label: "Meet Ivy" },
  { href: "/ivy/picks", label: "Ivy's Picks" },
  { href: "/ivy/trades", label: "Ivy's Trades" },
];

export default function IvyLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    api.system.health().then(setHealth).catch(() => {});
  }, []);

  let stripText: string | null = null;
  let pulse = false;
  if (health?.refresh_in_progress) {
    stripText = "Ivy is refreshing her data…";
    pulse = true;
  } else if (health?.last_refreshed_at) {
    stripText = `Data as of ${timeAgo(health.last_refreshed_at)}`;
  }

  return (
    <div className="mx-auto max-w-4xl px-4">
      <div className="pt-6">
        {stripText && (
          <p
            className={`text-[11px] text-muted-foreground mb-1${
              pulse ? " animate-pulse" : ""
            }`}
          >
            {stripText}
          </p>
        )}
        <nav className="flex gap-1 border-b mb-6">
          {tabs.map(({ href, label }) => {
            const active =
              href === "/ivy" ? pathname === "/ivy" : pathname.startsWith(href);
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
      </div>
      {children}
    </div>
  );
}
