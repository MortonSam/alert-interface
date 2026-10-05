import type { BriefingResponse, BriefingSentence } from "@/lib/api";
import { computedHowLine, insightAsOfLine } from "@/lib/insightHeadline";

export type { BriefingInput, BriefingResponse, BriefingSentence } from "@/lib/api";

/** The Overview's block labels, by sentence key. A key the API adds later renders unlabelled until named here. */
export const BLOCK_LABELS: Record<string, string> = { profile: "What it is", happening: "What's been happening" };

/** Phrases in block text that open a glossary entry in place, mapped to the glossary key. Longest first so
 * "52-week high" wins over any shorter overlap. */
export const GLOSSARY_LINKS: ReadonlyArray<readonly [string, string]> = [
  ["52-week high", "52-week high"],
  ["after the close", "after the close"],
  ["before the open", "before the open"],
  ["implied move", "implied move"],
  ["1-day move", "1-day move"],
];

export interface TextPart { text: string; term?: string }

/** Split a block's text into plain runs and glossary-linked runs, in order. Pure; the component wraps the linked runs. */
export function splitTerms(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let rest = text;
  while (rest.length) {
    let best: { index: number; phrase: string; term: string } | null = null;
    for (const [phrase, term] of GLOSSARY_LINKS) {
      const index = rest.indexOf(phrase);
      if (index >= 0 && (!best || index < best.index || (index === best.index && phrase.length > best.phrase.length))) best = { index, phrase, term };
    }
    if (!best) { parts.push({ text: rest }); break; }
    if (best.index > 0) parts.push({ text: rest.slice(0, best.index) });
    parts.push({ text: best.phrase, term: best.term });
    rest = rest.slice(best.index + best.phrase.length);
  }
  return parts;
}

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
