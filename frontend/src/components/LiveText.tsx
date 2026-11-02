"use client";

import type { BriefingInput } from "@/lib/api";
import { liveParts } from "@/lib/liveFigures";

/** A research note's text with each live figure marked by its receipt (name and as-of date): the API fills the figure from today's
 * stored value every time the note is read (backend services/note_live). */
export default function LiveText({ text, inputs }: { text: string; inputs: BriefingInput[] | null | undefined }) {
  return (
    <>
      {liveParts(text, inputs).map((p, i) =>
        p.tip ? (
          <span key={i} data-live-figure title={p.tip} className="explain-term">{p.text}</span>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
