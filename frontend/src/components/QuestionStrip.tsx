"use client";

import { useEffect, useState } from "react";
import posthog from "posthog-js";
import ExplainTip from "@/components/ticker/ExplainTip";
import { api, type QuestionsResponse } from "@/lib/api";
import { splitTerms } from "@/lib/briefing";
import { answerParts, hasQuestions, questionsHeader } from "@/lib/questions";
import { insightAsOfLine } from "@/lib/insightHeadline";

/**
 * The question strip under "What's been happening": up to four questions this stock's own data raises, each expanding
 * in place (one open at a time) to an answer built from stored rows. Every number in an answer shows its receipt on
 * hover; glossary terms link once per answer. Nothing here is typed: questions, answers, dates and receipts come from
 * the API; only the header copy is the page's own. Opening a question records a question_opened event.
 */
export function QuestionStrip({ symbol }: { symbol: string }) {
  const [data, setData] = useState<QuestionsResponse | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    setData(null); setOpen(null);
    api.tickers.questions(symbol).then(setData).catch(() => setData(null));
  }, [symbol]);
  if (!hasQuestions(data)) return null;
  const toggle = (key: string) => {
    const next = open === key ? null : key;
    setOpen(next);
    if (next) {
      try { posthog.capture("question_opened", { ticker: symbol, question: key }); } catch { /* analytics never breaks the page */ }
    }
  };
  return (
    <div className="mt-10 max-w-[65ch]">
      <p className="font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground mb-3">{questionsHeader(data!.name ?? symbol)}</p>
      <ul className="divide-y divide-border border-y border-border">
        {data!.questions.map((q) => {
          const isOpen = open === q.key;
          const asOf = insightAsOfLine(q.as_of);
          return (
            <li key={q.key}>
              <button type="button" onClick={() => toggle(q.key)} aria-expanded={isOpen} className="w-full text-left py-3 flex items-baseline justify-between gap-4 hover:text-primary transition-colors">
                <span className="text-base text-foreground/90">{q.question}</span>
                <span aria-hidden className="font-mono text-xs text-muted-foreground">{isOpen ? "−" : "+"}</span>
              </button>
              {isOpen && (
                <div className="pb-4 text-sm leading-relaxed">
                  <p className="text-foreground/90">
                    {answerParts(q.data, q.inputs).map((part, j) =>
                      part.receipt !== undefined ? (
                        <span key={j} title={part.receipt ?? undefined} className="font-semibold tabular-nums underline decoration-dotted underline-offset-4 cursor-help">{part.text}</span>
                      ) : part.term ? (
                        <ExplainTip key={j} term={part.term}><span className="underline decoration-dotted underline-offset-4 cursor-help">{part.text}</span></ExplainTip>
                      ) : (
                        <span key={j}>{part.text}</span>
                      ),
                    )}
                  </p>
                  <p className="text-muted-foreground mt-2">
                    {dedupeAgainst(q.data, q.idea).map((part, j) =>
                      part.term ? (
                        <ExplainTip key={j} term={part.term}><span className="underline decoration-dotted underline-offset-4 cursor-help">{part.text}</span></ExplainTip>
                      ) : (
                        <span key={j}>{part.text}</span>
                      ),
                    )}
                  </p>
                  {asOf && <p className="font-mono text-[11px] text-muted-foreground/70 mt-2">{asOf}</p>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Glossary links in the idea sentence skip any term the data sentence already linked: one link per term per answer. */
function dedupeAgainst(data: string, idea: string) {
  const used = new Set(splitTerms(data).filter((p) => p.term).map((p) => p.term as string));
  return splitTerms(idea).map((p) => (p.term && used.has(p.term) ? { text: p.text } : p));
}
