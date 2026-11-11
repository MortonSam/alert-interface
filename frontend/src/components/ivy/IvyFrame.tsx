"use client";

import { priceSourceLine } from "@/lib/freshness";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type HealthStatus } from "@/lib/api";
import { IvyFlag, useIvyMode } from "@/lib/useIvyMode";

const tabs = [
  { href: "/ivy", label: "Meet Ivy" },
  { href: "/ivy/desk", label: "Ivy's Desk" },
  { href: "/ivy/trades", label: "Ivy's Trades" },
];

/**
 * The old Ivy's tabs and price note stay until the walkthrough is on (lib/useIvyMode); the one new page brings its own frame.
 * The flag arrives with the page, as the server read it (app/ivy/layout), so the first paint is already the right Ivy and never
 * a blank while the browser asks (Sam, 2026-11-11).
 */
export default function IvyFrame({ walkthrough, children }: { walkthrough: boolean; children: React.ReactNode }) {
  return (
    <IvyFlag.Provider value={walkthrough}>
      <Frame>{children}</Frame>
    </IvyFlag.Provider>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  const ivy = useIvyMode();
  return ivy.mode === "walkthrough" ? <>{children}</> : <OldIvyLayout>{children}</OldIvyLayout>;
}

function OldIvyLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    api.system.health().then(setHealth).catch(() => {});
  }, []);

  // the price delay note alone: the refresh's state and a dataset's age are Sam's (the digest and the phone alert), never a visitor's (2026-11-10)
  const stripText: string | null = health ? priceSourceLine(health.cadence) : null;
  const pulse = false;

  const isWide = pathname === "/ivy" || pathname === "/ivy/desk";
  const widthClass = isWide ? "max-w-6xl" : "max-w-4xl";

  return (
    <div className={`mx-auto ${widthClass} px-4`}>
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
        <nav className="flex flex-wrap gap-1 border-b mb-6">
          {tabs.map(({ href, label }) => {
            const active =
              href === "/ivy" ? pathname === "/ivy" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={
                  active
                    ? "tap px-4 py-2 text-sm font-semibold text-foreground border-b-2 border-primary -mb-px"
                    : "tap px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors -mb-px border-b-2 border-transparent"
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
