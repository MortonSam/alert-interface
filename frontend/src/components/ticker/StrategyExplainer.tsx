"use client";

import { useState } from "react";
import { type StrategyData } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  type StrategyType, type Outlook, OUTLOOK_STRATEGIES, isMultiLeg,
} from "./shared";
import StrategyCard from "./StrategyCard";
import MultiLegStrategyCard from "./MultiLegStrategyCard";

export default function StrategyExplainer({ data, symbol }: { data: StrategyData; symbol: string }) {
  const [open, setOpen] = useState(false);
  const [outlook, setOutlook] = useState<Outlook>("bullish");

  return (
    <div className="mt-6 rounded-lg border bg-card overflow-visible">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-medium hover:bg-muted/30 transition-colors text-left"
        aria-expanded={open}
      >
        <span>Directional strategy explainer — {symbol}</span>
        <span className="text-muted-foreground text-xs shrink-0 ml-4">{open ? "\u25b2 Collapse" : "\u25bc Expand"}</span>
      </button>

      {open && (
        <div className="border-t px-5 py-4 space-y-5">
          <p className="text-xs text-muted-foreground italic leading-relaxed">
            Educational only — not investment advice. Payoff diagrams show at-expiration outcomes
            per share using real bid/ask mid-prices from the {data.expiration} expiration.
            Options are leveraged instruments; actual outcomes depend on timing, assignment, and
            transaction costs.
          </p>

          {/* Outlook tabs */}
          <div className="flex gap-1">
            {(["bullish", "bearish", "neutral"] as Outlook[]).map((o) => (
              <button
                key={o}
                onClick={() => setOutlook(o)}
                className={cn(
                  "px-3 py-1 rounded text-xs font-medium capitalize transition-colors",
                  outlook === o
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted",
                )}
              >
                {o.charAt(0).toUpperCase() + o.slice(1)}
              </button>
            ))}
          </div>

          {/* Implied range legend */}
          {data.implied_range_low != null && data.implied_range_high != null && (
            <p className="text-xs text-muted-foreground">
              <span className="inline-block w-3 h-3 rounded-sm bg-muted opacity-80 mr-1.5 align-middle" />
              Shaded band = implied range ${data.implied_range_low.toFixed(2)}–${data.implied_range_high.toFixed(2)} by {data.expiration}
            </p>
          )}

          {/* Strategy cards */}
          <div className="space-y-4">
            {OUTLOOK_STRATEGIES[outlook].map((s) =>
              isMultiLeg(s) ? (
                <MultiLegStrategyCard key={s} strategy={s} data={data} />
              ) : (
                <StrategyCard key={s} strategy={s as StrategyType} data={data} />
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
