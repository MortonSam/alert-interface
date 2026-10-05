"use client";

import type { BriefingSentence } from "@/lib/api";
import ExplainTip from "@/components/ticker/ExplainTip";
import { BLOCK_LABELS, sentenceReceipt, sourceLine, splitTerms } from "@/lib/briefing";

/**
 * The Overview: the API's blocks ("What it is", "What's been happening") in the overview's display type. Glossary
 * terms in the text are underlined links that open the existing glossary entry in place. Each block shows how it was
 * computed and the date it rests on when hovered or focused, and a Sources expander lists every input with its own
 * date. Nothing here is typed: the text, rules, dates and inputs all come from the API; only the block labels and
 * the glossary are the page's own. The same component serves the ticker page and the home page's featured example.
 */
export function Briefing({ sentences }: { sentences: BriefingSentence[] }) {
  if (!sentences.length) return null;
  return (
    <div className="space-y-8 max-w-[65ch]">
      {sentences.map((s, i) => {
        const r = sentenceReceipt(s);
        const receipt = [r.how, r.asOf].filter(Boolean).join(" · ");
        return (
          <div key={s.key + i} className="group relative" tabIndex={0}>
            <p className="font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground mb-2">{BLOCK_LABELS[s.key] ?? s.key}</p>
            <p className="text-lg text-foreground/90 leading-relaxed">
              {splitTerms(s.text).map((part, j) =>
                part.term ? (
                  <ExplainTip key={j} term={part.term}>
                    <span className="underline decoration-dotted underline-offset-4 cursor-help">{part.text}</span>
                  </ExplainTip>
                ) : (
                  <span key={j}>{part.text}</span>
                ),
              )}
            </p>
            {receipt && (
              <span role="tooltip" className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-[28rem] max-w-[80vw] rounded-lg border border-border bg-background px-3 py-2 font-sans text-xs leading-relaxed text-muted-foreground shadow-lg group-hover:block group-focus-within:block">
                {receipt}
              </span>
            )}
          </div>
        );
      })}
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none font-mono uppercase tracking-[.16em] text-[11px]">Sources</summary>
        <ul className="mt-2 space-y-1.5">
          {sentences.map((s, i) => (
            <li key={s.key + i}>
              <span className="font-mono uppercase tracking-[.12em] text-[10px] text-muted-foreground/70">{BLOCK_LABELS[s.key] ?? s.key}</span>
              <ul className="ml-3 mt-0.5 space-y-0.5">
                {s.inputs.map((inp, j) => (
                  <li key={inp.name + j}>{sourceLine(inp)}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
