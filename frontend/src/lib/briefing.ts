import type { BriefingResponse, BriefingSentence } from "@/lib/api";
import { computedHowLine, insightAsOfLine } from "@/lib/insightHeadline";

export type { BriefingInput, BriefingResponse, BriefingSentence } from "@/lib/api";

/** The Overview's block labels, by sentence key. A key the API adds later renders unlabelled until named here. */
export const BLOCK_LABELS: Record<string, string> = { profile: "What it is", happening: "What's been happening" };

/** Glossary terms the Overview links, as [phrase in the text, glossary key]. Longest first so "52-week high" wins over
 * any shorter overlap. Only whole words match ("estimated" is not "estimate"), and each term links once per block. */
export const GLOSSARY_LINKS: ReadonlyArray<readonly [string, string]> = [
  ["52-week high", "52-week high"],
  ["after the close", "after the close"],
  ["before the open", "before the open"],
  ["implied move", "implied move"],
  ["1-day move", "1-day move"],
  ["market cap", "market cap"],
  ["estimate", "estimate"],
  ["sector", "sector"],
  ["beat", "beat"],
  ["EPS", "eps"],
  ["realized volatility", "realized volatility"],
  ["ex-dividend", "ex-dividend"],
  ["straddle", "straddle"],
  ["upgrade", "upgrade"],
];

export interface TextPart { text: string; term?: string }

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Split a block's text into plain runs and glossary-linked runs: the first whole-word occurrence of each term, in order. Pure. */
export function splitTerms(text: string): TextPart[] {
  const hits: { index: number; phrase: string; term: string }[] = [];
  for (const [phrase, term] of GLOSSARY_LINKS) {
    const m = new RegExp(`(^|[^A-Za-z0-9-])(${escape(phrase)})(?![A-Za-z0-9-])`).exec(text);
    if (m && m.index >= 0) hits.push({ index: m.index + m[1].length, phrase, term });
  }
  hits.sort((a, b) => a.index - b.index || b.phrase.length - a.phrase.length);
  const parts: TextPart[] = [];
  let cursor = 0;
  for (const h of hits) {
    if (h.index < cursor) continue;                       // inside a longer term already linked
    if (h.index > cursor) parts.push({ text: text.slice(cursor, h.index) });
    parts.push({ text: h.phrase, term: h.term });
    cursor = h.index + h.phrase.length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
}

/** The receipt: `what` and `asOf` are the two short hover lines; `how` (the full rule) is for the Sources expander only. */
export function sentenceReceipt(s: BriefingSentence, today: Date = new Date()): { what: string; asOf: string | null; how: string | null } {
  const future = !!s.as_of && s.as_of > today.toISOString().slice(0, 10);          // an as-of is when we knew; a day ahead is never shown
  return { what: BLOCK_LABELS[s.key] ?? s.key, asOf: future ? null : insightAsOfLine(s.as_of), how: computedHowLine(s.rule) };
}

/** One line per input for the Sources list: "name: value (as of …; source)". Dates come from the input itself. */
export function sourceLine(i: { name: string; value: string; as_of: string | null; source: string | null }): string {
  const asOf = i.as_of && /^\d{4}-\d{2}-\d{2}$/.test(i.as_of) ? insightAsOfLine(i.as_of) : i.as_of;
  const tail = [asOf, i.source].filter(Boolean).join("; ");
  return `${i.name}: ${i.value}` + (tail ? ` (${tail})` : "");
}

/** The blocks as one string, in API order (tests and plain-text uses). */
export function briefingParagraph(sentences: BriefingSentence[]): string {
  return sentences.map((s) => s.text).join(" ");
}

export function hasBriefing(b: BriefingResponse | null | undefined): b is BriefingResponse {
  return !!b && Array.isArray(b.sentences) && b.sentences.length > 0;
}
