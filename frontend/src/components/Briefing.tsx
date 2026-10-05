import type { BriefingSentence } from "@/lib/api";
import { sentenceReceipt, sourceLine } from "@/lib/briefing";

/**
 * The overview briefing: the API's templated sentences as one paragraph in the overview's display type. Each
 * sentence shows how it was computed and the date it rests on when hovered or focused, and a Sources expander lists
 * every input with its own date. Nothing here is typed: the text, rules, dates and inputs all come from the API.
 * The same component serves the ticker page and the home page's featured example.
 */
export function Briefing({ sentences }: { sentences: BriefingSentence[] }) {
  if (!sentences.length) return null;
  return (
    <div>
      <p className="text-2xl font-display text-foreground/80 leading-relaxed">
        {sentences.map((s, i) => {
          const r = sentenceReceipt(s);
          const receipt = [r.how, r.asOf].filter(Boolean).join(" · ");
          return (
            <span key={s.key + i} className="group relative" tabIndex={0}>
              <span className="decoration-dotted underline-offset-4 group-hover:underline group-focus:underline">{s.text}</span>
              {i < sentences.length - 1 ? " " : ""}
              {receipt && (
                <span role="tooltip" className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-[28rem] max-w-[80vw] rounded-lg border border-border bg-background px-3 py-2 font-sans text-xs leading-relaxed text-muted-foreground shadow-lg group-hover:block group-focus:block">
                  {receipt}
                </span>
              )}
            </span>
          );
        })}
      </p>
      <details className="mt-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none font-mono uppercase tracking-[.16em] text-[11px]">Sources</summary>
        <ul className="mt-2 space-y-1.5">
          {sentences.map((s, i) => (
            <li key={s.key + i}>
              <span className="font-mono uppercase tracking-[.12em] text-[10px] text-muted-foreground/70">{s.key}</span>
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
