import type { BriefingInput, QuestionAnswer } from "@/lib/api";
import { splitTerms, type TextPart } from "@/lib/briefing";
import { insightAsOfLine } from "@/lib/insightHeadline";

export type { QuestionAnswer } from "@/lib/api";

/** The strip's header. Proposed copy, flagged for approval. */
export function questionsHeader(shortName: string): string {
  return `Questions about ${shortName}, answered by Ivy from this page's data`;
}

/** One token per quantity: a date ("Oct 14, 2026"), an amount ("$1,213.37", "-$0.46"), a percentage ("+3.0%", "±7.0%"), a count
 * ("1,254"). Alternation order matters: dates first, then amounts, then percentages, then bare numbers. "1-day" and "20-day" name
 * windows and are left as words. */
const DATE = String.raw`(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}`;
const AMOUNT = String.raw`[+\-±]?\$\d+(?:,\d{3})*(?:\.\d+)?`;
const PERCENT = String.raw`[+\-±]?\d+(?:,\d{3})*(?:\.\d+)?%`;
const COUNT = String.raw`\d+(?:,\d{3})*(?:\.\d+)?(?!-day|\d|[.,]\d|%)`;
export const QUANTITY = new RegExp(String.raw`(?<![\w$.])(?:${DATE}|${AMOUNT}|${PERCENT}|${COUNT})`, "g");

/** The receipt behind a quantity in an answer: the input whose value contains it, as "name: value (as of …; source)". */
export function receiptFor(token: string, inputs: BriefingInput[]): string | null {
  const bare = token.replace(/^[+\-±]+/, "");
  const digits = bare.replace(/[^0-9.,]/g, "");
  const hit = inputs.find((i) => i.value.includes(bare)) ?? inputs.find((i) => i.value.replace(/[^0-9.,]/g, "") === digits)
    ?? inputs.find((i) => i.value.replace(/[^0-9.,]/g, "").includes(digits));
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
  for (const m of text.matchAll(QUANTITY)) {
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

/** "Declared Sep 30, 2026" | "Estimated, as of Oct 6, 2026" | "As of Oct 5, 2026"; null for no date or a date after today
 * (an as-of is when we knew a fact; a future one is a bug the page refuses to show). */
export function asOfLabel(iso: string | null | undefined, kind: string | null | undefined, today: Date = new Date()): string | null {
  const line = insightAsOfLine(iso ?? null);
  if (!line || !iso) return null;
  const todayIso = today.toISOString().slice(0, 10);
  if (iso > todayIso) return null;
  const when = line.replace(/^As of /, "");
  if (kind === "declared") return `Declared ${when}`;
  if (kind === "estimated") return `Estimated, as of ${when}`;
  return line;
}

export function hasQuestions(r: { questions?: QuestionAnswer[] } | null | undefined): boolean {
  return !!r && Array.isArray(r.questions) && r.questions.length > 0;
}
