"use client";

import { useEffect, useState } from "react";
import DiscoverCard from "@/components/DiscoverCard";
import { api, type SuggestionItem } from "@/lib/api";

const ACCENT = { border: "hover:border-primary/40", text: "group-hover:text-primary" } as const;

export default function IvyPicksPage() {
  const [suggestions, setSuggestions] = useState<SuggestionItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.discover.suggestions(12);
        if (!cancelled) setSuggestions(data.items);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 py-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-border bg-card p-4 animate-pulse">
            <div className="flex items-start justify-between mb-2">
              <div className="h-5 w-16 bg-muted rounded" />
              <div className="h-4 w-14 bg-muted rounded" />
            </div>
            <div className="h-3.5 w-28 bg-muted rounded mb-3" />
            <div className="h-6 w-20 bg-muted rounded-full" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-5 py-4 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!suggestions || suggestions.length === 0) {
    return (
      <div className="rounded-xl border border-dashed px-8 py-12 text-center">
        <p className="text-lg font-medium">No standout setups right now</p>
        <p className="text-sm text-muted-foreground mt-1">
          Check back later for fresh picks from Ivy.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 py-4">
      {suggestions.map((item) => (
        <DiscoverCard
          key={item.symbol}
          symbol={item.symbol}
          name={item.name}
          accent={ACCENT}
          insight={item.insight}
          volRegime={item.vol_regime}
        />
      ))}
    </div>
  );
}
