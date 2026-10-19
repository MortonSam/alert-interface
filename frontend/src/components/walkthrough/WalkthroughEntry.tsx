"use client";

import { useCallback, useEffect, useState } from "react";
import { entryLine, fetchWalkthrough, type Walkthrough } from "@/lib/walkthrough";
import WalkthroughOverlay, { screenFromParam, screenParam, type Screen } from "./Walkthrough";

/** The line under the company name on a ticker page, and the walkthrough it opens. Shown only when a walkthrough is stored;
 *  ?learn=1..7, ?learn=summary or ?learn=compare&with=AAPL opens it at that screen (the home page's entry links here). */
export default function WalkthroughEntry({ symbol }: { symbol: string }) {
  const [w, setW] = useState<Walkthrough | null>(null);
  const [open, setOpen] = useState<Screen | null>(null);

  useEffect(() => {
    let live = true;
    fetchWalkthrough(symbol).then((r) => {
      if (!live || !r) return;
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
  const line = entryLine(w.name, w.minutes);
  return (
    <>
      <p className="mt-2 text-sm text-muted-foreground">
        {line.lead}{" "}
        <button type="button" onClick={() => { const s: Screen = { kind: "step", i: 0 }; setOpen(s); sync(s); }}
          className="tap font-medium text-primary underline-offset-4 hover:underline">
          {line.action}
        </button>
      </p>
      {open && <WalkthroughOverlay w={w} initial={open} onScreen={sync} onClose={() => { setOpen(null); sync(null); }} />}
    </>
  );
}
