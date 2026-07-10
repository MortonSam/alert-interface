"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import GLOSSARY from "@/lib/glossary";

// Global close function — opening one ExplainTip closes any other
let globalClose: (() => void) | null = null;

export type ExplainMetric =
  | "iv_rv_spread"
  | "rv_rank"
  | "expected_move"
  | "put_call"
  | "beat_drop_pattern";

export default function ExplainTip({
  term,
  metric,
  symbol,
  children,
}: {
  /** Glossary key — must match a key in glossary.ts */
  term: string;
  /** If provided, fetches a contextual explanation on open */
  metric?: ExplainMetric;
  /** Required when metric is set */
  symbol?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const definition = GLOSSARY[term.toLowerCase()] ?? null;

  const doOpen = useCallback(() => {
    // Close any other open ExplainTip
    if (globalClose && globalClose !== doClose) globalClose();
    if (ref.current) {
      setRect(ref.current.getBoundingClientRect());
      setOpen(true);
      globalClose = doClose;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doClose = useCallback(() => {
    setOpen(false);
    setRect(null);
    if (globalClose === doClose) globalClose = null;
  }, []);

  // Lazy fetch tier 2 on open
  useEffect(() => {
    if (!open || !metric || !symbol || context != null) return;
    setLoading(true);
    fetch(`/api/v1/tickers/explain/${encodeURIComponent(symbol)}/${metric}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.content && data.content !== "") {
          setContext(data.content);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open, metric, symbol, context]);

  // Click-away + Esc to dismiss
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") doClose();
    }
    function onClick(e: MouseEvent) {
      if (
        ref.current && !ref.current.contains(e.target as Node) &&
        cardRef.current && !cardRef.current.contains(e.target as Node)
      ) {
        doClose();
      }
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("touchstart", onClick as EventListener);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("touchstart", onClick as EventListener);
    };
  }, [open, doClose]);

  // Recompute position on scroll/resize while open
  useEffect(() => {
    if (!open) return;
    function reposition() {
      if (ref.current) setRect(ref.current.getBoundingClientRect());
    }
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open]);

  if (!definition) {
    // No glossary entry — render children plain
    return <>{children}</>;
  }

  const vw = typeof window !== "undefined" ? window.innerWidth : 1200;
  const cardWidth = 280;

  return (
    <>
      <span
        ref={ref}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          open ? doClose() : doOpen();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            open ? doClose() : doOpen();
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={open}
        className="inline-flex items-center gap-0.5 cursor-help decoration-dotted underline underline-offset-2 decoration-muted-foreground/50"
      >
        {children}
        <span className="text-muted-foreground/50 text-[10px] leading-none select-none" aria-hidden>
          &#9432;
        </span>
      </span>
      {open &&
        rect &&
        createPortal(
          <div
            ref={cardRef}
            role="dialog"
            aria-label={`Definition of ${term}`}
            style={{
              position: "fixed",
              top: rect.top - 8,
              left: Math.max(8, Math.min(vw - cardWidth - 8, rect.left + rect.width / 2 - cardWidth / 2)),
              transform: "translateY(-100%)",
              zIndex: 9999,
              width: cardWidth,
            }}
            className="rounded-lg border border-border bg-popover px-4 py-3 text-popover-foreground shadow-xl"
          >
            <p className="text-xs font-semibold leading-snug">{definition}</p>
            {loading && (
              <div className="mt-2 space-y-1.5 animate-pulse">
                <div className="h-2.5 bg-muted rounded w-full" />
                <div className="h-2.5 bg-muted rounded w-4/5" />
              </div>
            )}
            {!loading && context && (
              <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{context}</p>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}
