import type { BriefingResponse, BriefingSentence } from "@/lib/api";
import { computedHowLine, insightAsOfLine } from "@/lib/insightHeadline";

export type { BriefingInput, BriefingResponse, BriefingSentence } from "@/lib/api";

/** The sentences as one paragraph, in the order the API gives them. */
export function briefingParagraph(sentences: BriefingSentence[]): string {
  return sentences.map((s) => s.text).join(" ");
}

/** The receipt shown on hover: how the sentence was computed and the date it rests on. */
export function sentenceReceipt(s: BriefingSentence): { how: string | null; asOf: string | null } {
  return { how: computedHowLine(s.rule), asOf: insightAsOfLine(s.as_of) };
}

/** One line per input for the Sources list: "name: value (as of …; source)". Dates come from the input itself. */
export function sourceLine(i: { name: string; value: string; as_of: string | null; source: string | null }): string {
  const asOf = i.as_of && /^\d{4}-\d{2}-\d{2}$/.test(i.as_of) ? insightAsOfLine(i.as_of) : i.as_of;
  const tail = [asOf, i.source].filter(Boolean).join("; ");
  return `${i.name}: ${i.value}` + (tail ? ` (${tail})` : "");
}

export function hasBriefing(b: BriefingResponse | null | undefined): b is BriefingResponse {
  return !!b && Array.isArray(b.sentences) && b.sentences.length > 0;
}
