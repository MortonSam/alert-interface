"use client";

import { useId, useState, type ReactNode } from "react";

/** One collapsed-by-default control for the ticker page's folded detail (Evidence's distribution and peers, Options' details). */
export function Fold({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="mt-8 border-t border-border/60" data-testid={testId}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="tap flex w-full items-center justify-between py-4 text-left text-sm font-medium text-foreground hover:text-primary transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
      >
        <span>{label}</span>
        <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`shrink-0 transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      <div id={id} hidden={!open} className="pb-2">{open && children}</div>
    </div>
  );
}
