"use client";

import Link from "next/link";

interface DiscoverCardProps {
  symbol: string;
  name: string | null;
  price?: string; // pre-formatted, e.g. "$142.50"
  /** Primary badge (e.g. "EPS in 3d", "Beat +4.2%", "RV 92 · extreme") */
  badge?: React.ReactNode;
  /** One-line intelligence insight — muted, truncated */
  insight?: string | null;
  /** IV Rich / IV Cheap chip */
  volRegime?: string | null;
  /** Accent color for hover border and symbol hover color */
  accent: {
    border: string;   // e.g. "hover:border-amber-500/40"
    text: string;     // e.g. "group-hover:text-amber-500"
  };
}

const VOL_REGIME_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  iv_rich: { bg: "bg-orange-500/10", text: "text-orange-600 dark:text-orange-400", label: "IV Rich" },
  iv_cheap: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400", label: "IV Cheap" },
};

export default function DiscoverCard({
  symbol,
  name,
  price,
  badge,
  insight,
  volRegime,
  accent,
}: DiscoverCardProps) {
  const volChip = volRegime ? VOL_REGIME_STYLES[volRegime] : null;

  return (
    <Link
      href={`/tickers/${symbol}`}
      className={`rounded-xl border border-border bg-card p-4 ${accent.border} transition-colors group`}
    >
      {/* Row 1: symbol + price */}
      <div className="flex items-start justify-between mb-1">
        <span className={`font-display text-base font-bold text-foreground ${accent.text} transition-colors`}>
          {symbol}
        </span>
        {price && (
          <span className="font-mono text-xs text-muted-foreground">
            {price}
          </span>
        )}
      </div>

      {/* Row 2: company name */}
      <p className="text-xs text-muted-foreground truncate mb-2">
        {name ?? "\u2014"}
      </p>

      {/* Row 3: badge + vol regime chip */}
      {(badge || volChip) && (
        <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
          {badge}
          {volChip && (
            <span className={`inline-flex items-center rounded-full ${volChip.bg} ${volChip.text} px-2 py-0.5 text-[10px] font-semibold tracking-wide`}>
              {volChip.label}
            </span>
          )}
        </div>
      )}

      {/* Row 4: insight line */}
      {insight && (
        <p className="text-[11px] text-muted-foreground/70 truncate leading-snug mt-1">
          {insight}
        </p>
      )}
    </Link>
  );
}
