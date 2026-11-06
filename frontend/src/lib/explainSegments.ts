// Splits a sentence into plain text and glossary terms (lib/glossaryTerms `match`): the longest match wins, whole words only,
// acronyms and capitalized labels match their exact case, other strings any case.
import { TERMS } from "@/lib/glossaryTerms";

export interface Segment { text: string; key: string | null }

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const exactCase = (v: string) => v === v.toUpperCase() || /[&/]/.test(v);
const ENTRIES = TERMS.flatMap((t) => t.match.map((v) => ({ v, key: t.key }))).sort((a, b) => b.v.length - a.v.length);
// one case-insensitive pattern (no inline case modifiers, which older Safari rejects); exact-case terms are checked in keyFor
const PATTERN = new RegExp(ENTRIES.map(({ v }) => `(?<![A-Za-z0-9])${esc(v)}(?![A-Za-z0-9])`).join("|"), "gi");

function keyFor(found: string): string | null {
  const hit = ENTRIES.find(({ v }) => (exactCase(v) ? found === v : found.toLowerCase() === v.toLowerCase()));
  return hit ? hit.key : null;
}

export function explainSegments(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(PATTERN)) {
    const i = m.index ?? 0;
    if (i > last) out.push({ text: text.slice(last, i), key: null });
    out.push({ text: m[0], key: keyFor(m[0]) });            // an exact-case term in the wrong case ("iv" in prose) stays plain
    last = i + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), key: null });
  return out;
}

/** Each text's segments, a glossary term explained only at its first mention across the texts (in the order given, the order they
 *  read on screen): a later mention is plain text (Sam, 2026-10-29: one tooltip per term per walkthrough step). */
export function explainOnce(texts: (string | null | undefined)[]): Segment[][] {
  const seen = new Set<string>();
  return texts.map((t) => (t ? explainSegments(t) : []).map((seg) => {
    if (!seg.key) return seg;
    if (seen.has(seg.key)) return { text: seg.text, key: null };
    seen.add(seg.key);
    return seg;
  }));
}
