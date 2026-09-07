"use client";

import Link from "next/link";

interface DiscoverCardProps {
  symbol: string;
  name: string | null;
  sector?: string | null;
  industry?: string | null;
  price?: string; // pre-formatted, e.g. "$142.50"
  /** Primary badge (e.g. "EPS in 3d", "Beat +4.2%", "RV 92 · extreme") */
  badge?: React.ReactNode;
  /** One-line intelligence insight — muted, truncated */
  insight?: string | null;
  /** IV Rich / IV Cheap chip */
  volRegime?: string | null;
}

const VOL_REGIME_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  iv_rich: { bg: "bg-warning/10", text: "text-warning", label: "IV Rich" },
  iv_cheap: { bg: "bg-success/10", text: "text-success", label: "IV Cheap" },
};

export default function DiscoverCard({
  symbol,
  name,
  sector,
  industry,
  price,
  badge,
  insight,
  volRegime,
}: DiscoverCardProps) {
  const volChip = volRegime ? VOL_REGIME_STYLES[volRegime] : null;
  const context = [sector, industry].filter(Boolean).join(" \u00B7 ");

  return (
    <Link
      href={`/tickers/${symbol}`}
      className="rounded-xl border border-border/60 bg-transparent p-4 hover:border-primary/40 transition-colors group"
    >
      {/* Row 1: symbol + price */}
      <div className="flex items-start justify-between mb-1">
        <span className="font-display text-base font-bold text-foreground group-hover:text-primary transition-colors">
          {symbol}
        </span>
        {price && (
          <span className="font-mono text-xs text-muted-foreground">
            {price}
          </span>
        )}
      </div>

      {/* Row 2: company name */}
      <p className="text-xs text-muted-foreground truncate mb-0.5">
        {name ?? "\u2014"}
      </p>

      {/* Row 2b: sector · industry */}
      {context && (
        <p className="text-[11px] text-muted-foreground/60 truncate mb-2">
          {context}
        </p>
      )}

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
        <p className="text-xs text-muted-foreground truncate leading-snug mt-1">
          {insight}
        </p>
      )}
    </Link>
  );
}
