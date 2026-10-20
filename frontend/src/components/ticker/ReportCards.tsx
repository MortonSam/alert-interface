"use client";

import { useEffect, useRef, useState } from "react";
import type { HistoricalReaction } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BACK_TO_CHART, clickClearsPick, smoothScroll, type PickedReport } from "@/lib/evidenceViews";
import { fmtMove, reportCards, whyItMoved, type TypicalMove } from "@/lib/reportCards";

const FIRST_SHOWN = 8;

/** Newest-first report cards; tapping one opens its line built from stored facts. A report picked on the chart (`picked`) shows
 * every card if it is past the first FIRST_SHOWN, scrolls to its card and highlights it until the next click or tap anywhere else; `onBack` adds the
 * way back to the chart. */
export function ReportCards({ reactions, typical, picked = null, onBack }: {
  reactions: HistoricalReaction[]; typical: TypicalMove | null; picked?: PickedReport | null; onBack?: () => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const [lit, setLit] = useState<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const cards = reportCards(reactions);
  const byId = new Map(reactions.map((r) => [r.id, r]));
  const pickedAt = picked ? cards.findIndex((c) => c.eventDate === picked.date) : -1;
  const showAll = all || pickedAt >= FIRST_SHOWN;
  const shown = showAll ? cards : cards.slice(0, FIRST_SHOWN);

  useEffect(() => {
    if (!picked || pickedAt < 0) return;
    if (pickedAt >= FIRST_SHOWN) setAll(true);
    const el = listRef.current?.querySelector<HTMLElement>(`[data-event-date="${picked.date}"]`);
    el?.scrollIntoView({ block: "center", behavior: smoothScroll() });
    setLit(picked.date);
  }, [picked, pickedAt]);

  useEffect(() => {
    if (!lit) return;
    const clear = (e: MouseEvent) => { if (clickClearsPick(e, lit)) setLit(null); };
    document.addEventListener("click", clear, true);
    return () => document.removeEventListener("click", clear, true);
  }, [lit]);

  return (
    <div data-testid="report-cards">
      {onBack && (
        // sticky under the header and section nav, so it stays in reach after the jump to a card far down the list
        <div className="sticky top-[8.5rem] sm:top-28 z-10 mb-4 -mx-1">
          <button type="button" onClick={onBack} data-testid="back-to-chart"
            className="tap rounded-full border border-border bg-background/95 px-4 py-1.5 text-sm font-medium text-foreground/85 shadow-sm backdrop-blur hover:text-foreground transition-colors">
            {BACK_TO_CHART}
          </button>
        </div>
      )}
      <ul ref={listRef} className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {shown.map((c) => {
          const why = whyItMoved(byId.get(c.id)!, typical);
          const open = openId === c.id;
          return (
            <li key={c.id} data-event-date={c.eventDate}>
              <button
                type="button"
                aria-expanded={why ? open : undefined}
                disabled={!why}
                onClick={() => setOpenId(open ? null : c.id)}
                className={cn(
                  "w-full rounded-lg border bg-card px-4 py-3.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
                  open ? "border-primary/70" : "border-border hover:border-foreground/30",
                  lit === c.eventDate && "ring-2 ring-primary ring-offset-2 ring-offset-background",
                  !why && "cursor-default",
                )}
                data-testid="report-card"
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="text-base font-semibold text-foreground">{c.date}</span>
                  {c.timing && <span className="text-xs text-muted-foreground">{c.timing}</span>}
                </span>
                <span className={cn("mt-1 block text-sm", c.eps ? "text-foreground/90" : "text-muted-foreground")} data-testid="report-card-eps">
                  {c.eps ?? c.epsAbsent}
                </span>
                <span className="mt-3 grid grid-cols-3 gap-2">
                  {c.moves.map((m) => (
                    <span key={m.key} className="block">
                      <span className="block text-xs text-muted-foreground">{m.label}</span>
                      <span className={cn(
                        "block text-sm font-semibold tabular-nums",
                        m.value == null ? "text-muted-foreground font-normal"
                          : Number(m.value.toFixed(1)) > 0 ? "text-success" : Number(m.value.toFixed(1)) < 0 ? "text-destructive" : "text-foreground",
                      )} data-testid={`report-card-${m.key}`}>
                        {m.value == null ? "Not on file" : fmtMove(m.value)}
                      </span>
                    </span>
                  ))}
                </span>
                {open && why && (
                  <span className="mt-3 block border-t border-border/60 pt-3" data-testid="report-card-why">
                    <span className="block text-sm leading-relaxed text-foreground">{why.text}</span>
                    {why.receipt && <span className="mt-1.5 block text-xs text-muted-foreground">{why.receipt}</span>}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {cards.length > FIRST_SHOWN && (
        <button
          type="button"
          onClick={() => setAll(!showAll)}
          className="tap mt-3 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          {showAll ? "Show the latest 8 reports" : `Show all ${cards.length} reports`}
        </button>
      )}
    </div>
  );
}
