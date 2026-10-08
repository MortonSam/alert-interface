"use client";

import { useState } from "react";
import posthog from "posthog-js";
import ExplainTip from "@/components/ticker/ExplainTip";
import { api, ApiError, type QuestionAnswer } from "@/lib/api";
import { answerParts, asOfLabel } from "@/lib/questions";

/**
 * The free-text box under the question strip (shown only when the API says the ASK_IVY_ENABLED flag is on). Ivy answers
 * only from this stock's stored facts and says plainly when they do not cover the question; the model writes the words
 * but types no number: every number in the answer was inserted from a stored fact and carries its receipt on hover, and
 * the answer was checked against those facts before it is shown. Nothing here is typed by the page: the answer, its
 * receipts and its as-of come from the API; only the prompt copy and the error line are the page's own.
 */
export function AskIvy({ symbol, name, initialAnswer = null }: { symbol: string; name: string; initialAnswer?: QuestionAnswer | null }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QuestionAnswer | null>(initialAnswer);   // initialAnswer: a rendered answer for tests and previews
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null); setAnswer(null);
    try {
      const res = await api.tickers.ask(symbol, q);
      setAnswer(res.answer);
      try { posthog.capture("question_asked", { ticker: symbol, covered: res.answer.inputs.length > 0, cached: res.cached }); } catch { /* analytics never breaks the page */ }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ivy couldn't answer just now.");
    } finally {
      setBusy(false);
    }
  };

  const asOf = answer ? asOfLabel(answer.as_of, answer.as_of_kind) : null;
  return (
    <form onSubmit={submit} className="mt-6">
      <label htmlFor="ask-ivy" className="font-mono text-[11px] uppercase tracking-[.16em] text-muted-foreground">Ask Ivy about {name}</label>
      <p className="text-xs text-muted-foreground mt-1">She answers only from this page&apos;s stored data and says when it doesn&apos;t cover a question. No recommendations.</p>
      <div className="mt-2 flex gap-2">
        <input
          id="ask-ivy" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={300} disabled={busy}
          placeholder="Is it more volatile than usual?"
          className="flex-1 min-h-[44px] sm:min-h-0 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button type="submit" disabled={busy || !question.trim()} className="tap rounded-md border border-border px-3 py-2 text-sm hover:text-primary disabled:opacity-50 transition-colors">
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>
      {error && <p className="text-sm text-muted-foreground mt-3">{error}</p>}
      {answer && (
        <div className="mt-4 text-sm leading-relaxed">
          <p className="text-foreground/90">
            {answerParts(answer.data, answer.inputs).map((part, j) =>
              part.receipt !== undefined ? (
                <span key={j} data-quantity title={part.receipt ?? undefined} className="font-semibold underline decoration-dotted underline-offset-4 cursor-help">{part.text}</span>
              ) : part.term ? (
                <ExplainTip key={j} term={part.term}><span className="underline decoration-dotted underline-offset-4 cursor-help">{part.text}</span></ExplainTip>
              ) : (
                <span key={j}>{part.text}</span>
              ),
            )}
          </p>
          <p className="font-mono text-[11px] text-muted-foreground/70 mt-2" title={answer.rule}>{asOf ? `${asOf} · ` : ""}Checked against this page&apos;s stored facts</p>
        </div>
      )}
    </form>
  );
}
