"use client";

// The home page's note section: the most recently verified research note whose company has not reported since it
// was written (the API skips older notes, services/note_currency), rendered from the stored note (its ticker, its
// dates, its own fact figures, its verification counts). Never a sample. When no note qualifies, or the request
// fails, the section is not shown at all.

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type LatestVerifiedNote as Note } from "@/lib/api";
import { noteFacts, verificationLine } from "@/lib/latestNote";

const RATING_CLASS: Record<string, string> = {
  bullish: "bg-success/10 text-success border-success/25",
  neutral: "bg-cool/10 text-cool border-cool/25",
  bearish: "bg-destructive/10 text-destructive border-destructive/25",
};

export default function LatestVerifiedNote() {
  const [note, setNote] = useState<Note | null | undefined>(undefined);   // undefined: loading; null: none
  useEffect(() => {
    api.researchNotes.latestVerified().then(setNote).catch(() => setNote(null));   // a 404 (none yet) or any failure: the block says so
  }, []);

  if (!note) return null;          // loading, none current, or a failure: no section
  const facts = noteFacts(note.stats);
  const verified = verificationLine(note.verification_summary);
  const generated = new Date(note.generated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  return (
    <section className="max-w-3xl mx-auto px-4 sm:px-8 py-12 sm:py-24">
      <div className="text-center mb-12">
        <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
          See it in action
        </p>
        <h2 className="statement-h2 font-display font-bold text-foreground max-w-[20ch] mx-auto">
          The latest verified note
        </h2>
        <p className="text-sm text-muted-foreground mt-4 max-w-lg mx-auto">
          Rendered from the stored note: its own figures, its own words, and what the second model found.
        </p>
      </div>
    <div className="relative rounded-2xl border border-border bg-card" data-testid="latest-verified-note">
      <div className="flex items-center gap-2 px-5 py-2.5 border-b border-border bg-secondary/40">
        <span className="h-2 w-2 rounded-full bg-success" />
        <span className="font-mono text-[11px] text-muted-foreground">
          Generated {generated}{note.verified_at ? " \u00B7 verified" : ""}
        </span>
      </div>
      <div className="px-6 py-5 space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <Link href={`/tickers/${note.symbol}`} className="font-display text-2xl font-bold text-foreground hover:text-primary transition-colors">
              {note.symbol}
            </Link>
            {note.company_name && <p className="text-sm text-muted-foreground">{note.company_name}</p>}
          </div>
          {note.rating && (
            <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${RATING_CLASS[note.rating] ?? ""}`}>
              {note.rating}
            </span>
          )}
        </div>
        {facts.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {facts.map((f) => (
              <div key={f.label} className="border-l border-border pl-4">
                <p className="font-mono text-[10px] uppercase tracking-[.16em] text-muted-foreground">{f.label}</p>
                <p className="font-mono text-[22px] font-semibold leading-tight text-foreground tabular-nums">{f.value}</p>
                {f.sub && <p className="text-xs text-muted-foreground mt-0.5">{f.sub}</p>}
              </div>
            ))}
          </div>
        )}
        {note.highlights.length > 0 && (
          <div className="space-y-2">
            {note.highlights.map((h) => (
              <p key={h.lead} className="text-sm text-foreground/85"><span className="font-semibold text-foreground">{h.lead}.</span> {h.detail}</p>
            ))}
          </div>
        )}
        {verified && <p className="font-mono text-[11px] text-muted-foreground">{verified}</p>}
      </div>
      <div className="flex justify-center py-4 border-t border-border">
        <Link href={`/tickers/${note.symbol}`} className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
          Read the full note for {note.symbol}
        </Link>
      </div>
    </div>
    </section>
  );
}
