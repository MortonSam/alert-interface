"use client";

import { useState, type ReactNode } from "react";

/** The ticker page's folded detail (Options' details), styled as the walkthrough's "Go deeper" row (Sam's live review, 2026-10-20):
 * a native disclosure line in the section's own flow, no rule or full-width bar, so the closed state reads as part of the section
 * and adds no space of its own. Children render only once opened. */
export function Fold({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="mt-6 group" data-testid={testId} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="tap cursor-pointer select-none text-sm font-medium text-foreground/85 hover:text-foreground">{label}</summary>
      <div className="mt-3">{open && children}</div>
    </details>
  );
}
