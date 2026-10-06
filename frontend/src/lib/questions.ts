import type { BriefingInput, QuestionAnswer } from "@/lib/api";
import { splitTerms, type TextPart } from "@/lib/briefing";
import { insightAsOfLine } from "@/lib/insightHeadline";

export type { QuestionAnswer } from "@/lib/api";

/** The strip's header. Proposed copy, flagged for approval. */
export function questionsHeader(shortName: string): string {
  return `Questions about ${shortName}, answered by Ivy from this page's data`;
}

const NUMBER = /(?<![\d:])[+\-±$]?\$?\d+(?:,\d{3})*(?:\.\d+)?%?(?![\d:]|-day)/g;      // "1-day" and "20-day" name windows, not numbers

/** The receipt behind a number in an answer: the input whose value contains it, as "name: value (as of …; source)". */
export function receiptFor(token: string, inputs: BriefingInput[]): string | null {
  const bare = token.replace(/^[+\-±$]+/, "").replace(/%$/, "");
  const hit = inputs.find((i) => i.value.includes(bare)) ?? inputs.find((i) => i.value.replace(/[^0-9.,]/g, "").includes(bare.replace(/[^0-9.,]/g, "")));
  if (!hit) return null;
  const asOf = hit.as_of && /^\d{4}-\d{2}-\d{2}$/.test(hit.as_of) ? insightAsOfLine(hit.as_of) : hit.as_of;
  const tail = [asOf, hit.source].filter(Boolean).join("; ");
  return `${hit.name}: ${hit.value}` + (tail ? ` (${tail})` : "");
}

export interface AnswerPart extends TextPart { receipt?: string | null }

/** An answer's data sentence split into numbers (each with its receipt), glossary terms and plain runs, in order. Pure. */
export function answerParts(text: string, inputs: BriefingInput[]): AnswerPart[] {
  const out: AnswerPart[] = [];
  let cursor = 0;
  for (const m of text.matchAll(NUMBER)) {
    const idx = m.index ?? 0;
    if (idx > cursor) out.push(...splitTerms(text.slice(cursor, idx)));
    out.push({ text: m[0], receipt: receiptFor(m[0], inputs) });
    cursor = idx + m[0].length;
  }
  if (cursor < text.length) out.push(...splitTerms(text.slice(cursor)));
  return dedupeTerms(out);
}

/** One glossary link per term per answer: later occurrences fall back to plain text. */
function dedupeTerms(parts: AnswerPart[]): AnswerPart[] {
  const seen = new Set<string>();
  return parts.map((p) => {
    if (!p.term) return p;
    if (seen.has(p.term)) return { text: p.text };
    seen.add(p.term);
    return p;
  });
}

export function hasQuestions(r: { questions?: QuestionAnswer[] } | null | undefined): boolean {
  return !!r && Array.isArray(r.questions) && r.questions.length > 0;
}
