"use client";

import { useCallback, useEffect, useState } from "react";
import DiscoverCard from "@/components/DiscoverCard";
import { api, type SuggestionItem } from "@/lib/api";

export default function IvyPicksPage() {
  const [suggestions, setSuggestions] = useState<SuggestionItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSuggestions = useCallback(() => {
    setLoading(true);
    setError(null);
    api.discover.suggestions(10)
      .then((data) => setSuggestions(data.items))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadSuggestions(); }, [loadSuggestions]);

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
      <div className="rounded-xl border border-border bg-card px-6 py-10 text-center space-y-4">
        <p className="text-sm text-muted-foreground">
          Couldn&apos;t load Ivy&apos;s Picks right now.
        </p>
        <button
          onClick={() => { setError(null); setLoading(true); loadSuggestions(); }}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          Retry
        </button>
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
          insight={item.insight}
          volRegime={item.vol_regime}
        />
      ))}
    </div>
  );
}
