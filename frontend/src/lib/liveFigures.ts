// A research note's live figures (backend services/note_live, Sam 2026-11-02): a figure that changes every day (the price, a P/E,
// the market value, volatility, the move options price) is never written into a note; the note holds a slot the API fills from the
// stored receipt each time the note is read, and sends the receipts (live_inputs). Each filled figure is marked with its receipt's
// name and as-of date, as Ask Ivy's figures are.

import type { BriefingInput } from "@/lib/api";
import { fmtDate } from "@/lib/dates";

export interface LivePart {
  text: string;
  tip?: string;   // "last close, as of Oct 30, 2026": the tooltip on a filled figure
}

/** "last close, as of Oct 30, 2026"; the name alone when the receipt has no date. */
export function liveReceipt(input: BriefingInput): string {
  const day = fmtDate(input.as_of?.slice(0, 10) ?? null);
  return day ? `${input.name}, as of ${day}` : input.name;
}

/** The text split around every filled live figure, longest value first so "$215.38" is never read as "$215". */
export function liveParts(text: string, inputs: BriefingInput[] | null | undefined): LivePart[] {
  const live = (inputs ?? []).filter((i) => i.value);
  if (!text || live.length === 0) return [{ text }];
  const sorted = [...live].sort((a, b) => b.value.length - a.value.length);
  const escaped = sorted.map((i) => i.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`(${escaped.join("|")})`, "g");
  const out: LivePart[] = [];
  let cursor = 0;
  for (const m of text.matchAll(pattern)) {
    const at = m.index ?? 0;
    if (at > cursor) out.push({ text: text.slice(cursor, at) });
    const input = sorted.find((i) => i.value === m[0]);
    out.push({ text: m[0], tip: input ? liveReceipt(input) : undefined });
    cursor = at + m[0].length;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) });
  return out;
}

/** "Written Oct 30, 2026": the note's own date, never a time ago. */
export function writtenLabel(generatedAt: string | null | undefined): string | null {
  const day = fmtDate(generatedAt?.slice(0, 10) ?? null);
  return day ? `Written ${day}` : null;
}

/** A material filing newer than the note: "Not yet in this note: the 8-K filed Nov 2, 2026". The nightly writes the note again
 * from it (backend generate_notes), but within the night's AI budget, so the line never promises a time. */
export function pendingFilingLabel(p: { form: string; filed_on: string | null } | null | undefined): string | null {
  if (!p) return null;
  const day = fmtDate(p.filed_on?.slice(0, 10) ?? null);
  return day ? `Not yet in this note: the ${p.form} filed ${day}` : null;
}
