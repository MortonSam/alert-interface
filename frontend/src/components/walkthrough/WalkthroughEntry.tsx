"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchWalkthrough, researchEntry, type Walkthrough } from "@/lib/walkthrough";
import WalkthroughOverlay, { screenFromParam, screenParam, type Screen } from "./Walkthrough";
import { IvyMark } from "@/components/IvyMark";

/** The entry at the top of a ticker page's Research section (Sam, 2026-11-02; it sat under the company name before), and the
 *  walkthrough it opens. Shown only when a walkthrough is stored and the API says it has enough steps with data (`entry`); the API
 *  serves none while IVY_WALKTHROUGH_ENABLED is off, so the entry stays hidden;
 *  ?learn=1..7, ?learn=summary or ?learn=compare&with=AAPL opens it at that screen (the home page's entry links here). */
export default function WalkthroughEntry({ symbol }: { symbol: string }) {
  const [w, setW] = useState<Walkthrough | null>(null);
  const [open, setOpen] = useState<Screen | null>(null);

  useEffect(() => {
    let live = true;
    fetchWalkthrough(symbol).then((r) => {
      if (!live || !r || !r.entry) return;
      setW(r);
      const q = new URLSearchParams(window.location.search);
      if (q.get("learn")) setOpen(screenFromParam(q.get("learn"), q.get("with")));
    });
    return () => { live = false; };
  }, [symbol]);

  const sync = useCallback((s: Screen | null) => {
    const url = new URL(window.location.href);
    if (s) {
      url.searchParams.set("learn", screenParam(s));
      if (s.kind === "compare" && s.with) url.searchParams.set("with", s.with); else url.searchParams.delete("with");
    } else {
      url.searchParams.delete("learn");
      url.searchParams.delete("with");
    }
    window.history.replaceState(window.history.state, "", url.toString());
  }, []);

  if (!w) return null;
  const line = researchEntry(w.name, w.minutes);
  return (
    <>
      {/* the main invitation of the Research section (Sam, 2026-11-10): Ivy's mark, the orange accent used across the site, an arrow */}
      <button type="button" data-testid="walkthrough-entry" onClick={() => { const s: Screen = { kind: "step", i: 0 }; setOpen(s); sync(s); }}
        className="tap group mb-8 flex w-full items-center gap-4 rounded-xl border border-primary/50 bg-primary/[0.06] px-5 py-4 text-left hover:border-primary hover:bg-primary/10 transition-colors">
        <IvyMark size={32} className="shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block font-display text-lg font-semibold text-foreground">{line.action}</span>
          <span className="block text-xs text-muted-foreground mt-0.5">{line.length}</span>
        </span>
        <span aria-hidden="true" className="shrink-0 text-xl text-primary transition-transform group-hover:translate-x-0.5">→</span>
      </button>
      {open && <WalkthroughOverlay w={w} initial={open} onScreen={sync} onClose={() => { setOpen(null); sync(null); }} />}
    </>
  );
}
