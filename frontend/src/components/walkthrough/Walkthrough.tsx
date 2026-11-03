"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Ticker } from "@/lib/api";
import { matchTickers } from "@/lib/tickerSearch";
import {
  alreadyMet, compareLine, factFor, fetchCompare, fetchWalkthrough, learn, learnedElsewhere, readLearned,
  type CompareResult, type Learned, type WalkCheck, type WalkIdea, type WalkStep, type Walkthrough,
} from "@/lib/walkthrough";
import { WALK_COPY as T } from "@/lib/walkthroughCopy";
import Explained from "@/components/Explained";
import { explainOnce, type Segment } from "@/lib/explainSegments";
import { PeRangeChart, PriceVsMarketChart } from "./WalkthroughCharts";

export type Screen = { kind: "step"; i: number } | { kind: "summary" } | { kind: "compare"; with: string | null };

export function screenFromParam(learn: string | null, withSym: string | null): Screen {
  if (learn === "summary") return { kind: "summary" };
  if (learn === "compare") return { kind: "compare", with: withSym ? withSym.toUpperCase() : null };
  const n = Number(learn);
  return { kind: "step", i: Number.isInteger(n) && n >= 1 && n <= 7 ? n - 1 : 0 };
}

export function screenParam(s: Screen): string {
  return s.kind === "step" ? String(s.i + 1) : s.kind;
}

function IdeaBox({ idea, known, segments }: { idea: WalkIdea; known: { from: string; line: string } | null; segments?: Segment[] }) {
  return (
    <aside className="mt-6 rounded-xl border border-border bg-muted/40 px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{T.idea}</p>
      {known ? (
        <>
          <p className="mt-1.5 text-sm font-semibold text-foreground">{T.knownFrom(idea.title, known.from)}</p>
          <p className="mt-1 text-sm leading-relaxed text-foreground/85">{known.line}</p>
        </>
      ) : (
        <>
          <p className="mt-1.5 text-sm font-semibold text-foreground">{idea.title}</p>
          <p className="mt-1 text-sm leading-relaxed text-foreground/80"><Explained text={idea.text} segments={segments} /></p>
        </>
      )}
    </aside>
  );
}

function QuickCheck({ check, onDone, segs }: { check: WalkCheck; onDone: () => void; segs?: { question?: Segment[]; why?: Segment[] } }) {
  const [picked, setPicked] = useState<number | null>(null);
  const [skipped, setSkipped] = useState(false);
  if (skipped) return null;
  const done = picked !== null;
  return (
    <section className="mt-6" aria-label={T.quickCheck}>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{T.quickCheck}</p>
        {!done && (
          <button type="button" onClick={() => { setSkipped(true); onDone(); }} className="tap text-xs text-muted-foreground hover:text-foreground">
            {T.skip}
          </button>
        )}
      </div>
      <p className="mt-1.5 text-sm text-foreground"><Explained text={check.question} segments={segs?.question} /></p>
      <div className="mt-3 grid gap-2">
        {check.options.map((o, i) => {
          const right = i === check.answer;
          const state = !done ? "idle" : right ? "right" : i === picked ? "wrong" : "idle";
          return (
            <button
              key={o}
              type="button"
              disabled={done}
              onClick={() => { setPicked(i); onDone(); }}
              className={`tap text-left rounded-lg border px-3.5 py-2.5 text-sm transition-colors ${
                state === "right" ? "border-success/60 bg-success/10 text-foreground"
                  : state === "wrong" ? "border-destructive/60 bg-destructive/10 text-foreground"
                  : done ? "border-border text-muted-foreground" : "border-border text-foreground hover:border-foreground/30"
              }`}
            >
              {o}
            </button>
          );
        })}
      </div>
      {done && (
        <p className="mt-3 text-sm text-foreground/85" role="status">
          <span className="font-semibold">{picked === check.answer ? T.right : T.notQuite}</span> <Explained text={check.why} segments={segs?.why} />
        </p>
      )}
    </section>
  );
}

/** `preview`: the step's figures, sentences, quote and chart only, without the quick check, "The idea" or Go deeper (the /ivy page
 *  shows one step as a sample of the walkthrough, Sam 2026-11-03). */
export function StepScreen({ step, w, learned, others, preview = false }: { step: WalkStep; w: Walkthrough; learned: Learned; others: Record<string, Walkthrough | null>; preview?: boolean }) {
  const from = learnedElsewhere(step.idea, learned, w.symbol);
  const line = from && step.idea ? compareLine(factFor(others[from.symbol] ?? null, step.idea.concept), step.fact) : null;
  const known = from && line ? { from: others[from.symbol]?.name ?? from.name, line } : null;
  // order: numbers, Ivy's sentences, the quick check, then "The idea" once the visitor answers or skips (it never shows beside an open question).
  // A check whose answer the visitor has already met for this concept is not asked again: the line comparing the two stocks shows instead.
  const asks = !preview && step.status !== "absent" && !!step.check && !alreadyMet(step.check, learned);
  const [checked, setChecked] = useState(false);
  // a glossary term is explained at its first mention on the screen only, in reading order (Sam, 2026-10-29)
  const texts = [
    ...step.numbers.map((n) => n.label), ...step.sentences, ...(step.risks ?? []).map((r) => r.sentence), step.story,
    step.quote?.lead, step.quote?.text, asks ? step.check?.question : null, asks ? step.check?.why : null, known ? null : step.idea?.text,
  ];
  const once = useMemo(() => explainOnce(texts), [step, asks, !!known]);  // eslint-disable-line react-hooks/exhaustive-deps
  let at = 0;
  const seg = () => once[at++];
  const nLabels = step.numbers.map(() => seg());
  const sSegs = step.sentences.map(() => seg());
  const rSegs = (step.risks ?? []).map(() => seg());
  const storySeg = seg();
  const quoteSegs = { lead: seg(), text: seg() };
  const checkSegs = { question: seg(), why: seg() };
  const ideaSeg = seg();
  return (
    <div>
      <h2 className="font-display text-headline font-semibold text-foreground">{step.question}</h2>
      {step.status === "absent" ? (
        <p className="mt-5 font-display text-lg leading-relaxed text-foreground/80"><Explained text={step.absent} /></p>
      ) : (
        <>
          {step.numbers.length > 0 && (
            <div className={`mt-5 grid gap-4 ${step.numbers.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
              {step.numbers.map((n) => (
                <div key={n.label}>
                  <p className="font-sans text-[30px] sm:text-[36px] font-semibold leading-none tracking-tight text-foreground">{n.value}</p>
                  <p className="mt-1.5 text-[13px] text-foreground/85"><Explained text={n.label} segments={nLabels[step.numbers.indexOf(n)]} /></p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{n.as_of}</p>
                </div>
              ))}
            </div>
          )}
          <div className="mt-5 space-y-2.5 font-display text-[17px] sm:text-lg leading-relaxed text-foreground/90">
            {step.sentences.map((s, i) => <p key={s}><Explained text={s} segments={sSegs[i]} /></p>)}
            {step.risks && (
              <ul className="space-y-2.5">
                {step.risks.map((r, i) => (
                  <li key={r.n} className="border-l-2 border-primary/50 pl-3">
                    <Explained text={r.sentence} segments={rSegs[i]} />
                    {step.source?.url && (
                      <a href={step.source.url} target="_blank" rel="noopener noreferrer" className="ml-2 font-sans text-xs text-cool hover:text-cool/80">{T.readFiling}</a>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {step.story && <p><Explained text={step.story} segments={storySeg} /></p>}
          </div>
          {step.quote && (
            <figure className="mt-5" data-walk-quote>
              <figcaption className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"><Explained text={step.quote.lead} segments={quoteSegs.lead} /></figcaption>
              <blockquote className="mt-1.5 border-l-2 border-primary/50 pl-3 font-display text-[16px] leading-relaxed text-foreground/90">
                “<Explained text={step.quote.text} segments={quoteSegs.text} />”
                <a href={step.quote.source.url} target="_blank" rel="noopener noreferrer" className="ml-2 font-sans text-xs text-cool hover:text-foreground">{T.readFiling}</a>
              </blockquote>
            </figure>
          )}
          {step.chart?.kind === "price_vs_market" && <PriceVsMarketChart chart={step.chart} name={w.name} sector={w.sector} />}
          {step.chart?.kind === "pe_range" && <PeRangeChart chart={step.chart} />}
        </>
      )}
      {asks && step.check && <QuickCheck key={step.key} check={step.check} onDone={() => setChecked(true)} segs={checkSegs} />}
      {!preview && step.idea && (!asks || checked) && <IdeaBox idea={step.idea} known={known} segments={ideaSeg} />}
      {!preview && (step.deeper.length > 0 || step.source) && step.status !== "absent" && (
        <details className="mt-6 group">
          <summary className="tap cursor-pointer select-none text-sm font-medium text-foreground/85 hover:text-foreground">{T.goDeeper}</summary>
          <dl className="mt-3 divide-y divide-border/60 text-sm">
            {step.deeper.map((d) => (
              <div key={d.label + d.value} className="py-2 grid grid-cols-[1fr_auto] gap-x-3">
                <dt className="text-foreground/85">{d.label}</dt>
                <dd className="text-right text-foreground">{d.value}</dd>
                <dd className="col-span-2 text-[11px] text-muted-foreground">{d.as_of}</dd>
              </div>
            ))}
          </dl>
          {step.source?.url && (
            <a href={step.source.url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-xs text-cool hover:text-cool/80">{step.source.label}</a>
          )}
        </details>
      )}
    </div>
  );
}

function SummaryScreen({ w, onCompare, onAsk, onClose }: { w: Walkthrough; onCompare: () => void; onAsk: () => void; onClose: () => void }) {
  return (
    <div>
      <h2 className="font-display text-headline font-semibold">{T.summaryTitle(w.name)}</h2>
      <ol className="mt-5 space-y-2.5 font-display text-[17px] leading-relaxed">
        {w.summary.known.map((k) => (
          <li key={k.n} className="flex gap-3 text-foreground/90">
            <span className="font-sans text-xs text-muted-foreground pt-1.5 w-4 shrink-0">{k.n}</span>
            <span><Explained text={k.line} /></span>
          </li>
        ))}
      </ol>
      {w.summary.uncertain.length > 0 && (
        <>
          <h3 className="mt-7 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{T.uncertainTitle}</h3>
          <ul className="mt-2 space-y-1.5 text-sm text-foreground/85 list-disc pl-5">
            {w.summary.uncertain.map((u) => <li key={u}>{u}</li>)}
          </ul>
        </>
      )}
      {w.summary.concepts.length > 0 && (
        <>
          <h3 className="mt-7 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{T.conceptsTitle}</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {w.summary.concepts.map((c) => (
              <span key={c.concept} className="rounded-full border border-border px-3 py-1 text-xs text-foreground/85">{c.title}</span>
            ))}
          </div>
        </>
      )}
      <p className="mt-7 font-display text-[17px] text-foreground/90">{w.summary.closing}</p>
      <div className="mt-6 grid gap-2.5 sm:grid-cols-3">
        <button type="button" onClick={onCompare} className="tap rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground hover:opacity-90">
          {T.compareMove(w.name)}
        </button>
        {w.ask_enabled && (
          <button type="button" onClick={onAsk} className="tap rounded-xl border border-border px-4 py-3 text-sm font-semibold hover:border-foreground/40">
            {T.askMove}
          </button>
        )}
        <button type="button" onClick={onClose} className="tap rounded-xl border border-border px-4 py-3 text-sm font-semibold hover:border-foreground/40">
          {T.fullPageMove}
        </button>
      </div>
    </div>
  );
}

function CompareScreen({ w, other, setOther }: { w: Walkthrough; other: string | null; setOther: (s: string) => void }) {
  const [data, setData] = useState<CompareResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "missing">("idle");
  const [query, setQuery] = useState("");
  const [tickers, setTickers] = useState<Ticker[]>([]);
  useEffect(() => {
    if (!other) return;
    let live = true;
    setState("loading");
    fetchCompare(w.symbol, other).then((r) => { if (!live) return; setData(r); setState(r ? "idle" : "missing"); });
    return () => { live = false; };
  }, [w.symbol, other]);
  useEffect(() => {
    if (!query || tickers.length) return;
    api.tickers.list().then((t) => setTickers(t.filter((x) => x.index_member))).catch(() => {});
  }, [query, tickers.length]);
  const matches = useMemo(() => matchTickers(tickers, query, 6).filter((t) => t.symbol !== w.symbol), [tickers, query, w.symbol]);
  return (
    <div>
      <h2 className="font-display text-headline font-semibold">{T.compareTitle}</h2>
      <div className="mt-4 flex flex-wrap gap-2">
        {w.compare_choices.map((c) => (
          <button key={c.symbol} type="button" onClick={() => setOther(c.symbol)}
            className={`tap rounded-full border px-3.5 py-1.5 text-sm ${other === c.symbol ? "border-primary text-foreground bg-primary/10" : "border-border text-foreground/85 hover:border-foreground/30"}`}>
            {c.kind === "rival" ? T.rivalChoice(c.name, c.label) : T.rulerChoice(c.name)}
          </button>
        ))}
      </div>
      <label className="mt-3 block text-xs text-muted-foreground" htmlFor="walk-compare-search">{T.searchPrompt}</label>
      <input id="walk-compare-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={T.searchPlaceholder} autoComplete="off"
        className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40" />
      {matches.length > 0 && (
        <ul className="mt-1 rounded-lg border border-border divide-y divide-border/60">
          {matches.map((t) => (
            <li key={t.symbol}>
              <button type="button" onClick={() => { setOther(t.symbol); setQuery(""); }} className="tap w-full text-left px-3 py-2 text-sm hover:bg-muted">
                <span className="font-semibold">{t.symbol}</span> <span className="text-muted-foreground">{t.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {state === "loading" && <p className="mt-6 text-sm text-muted-foreground">{T.loading}</p>}
      {state === "missing" && other && <p className="mt-6 text-sm text-muted-foreground">{T.noWalkthrough(other)}</p>}
      {data && state === "idle" && (
        <>
          <table className="mt-6 w-full table-fixed text-sm">
            <thead>
              <tr>
                <th className="w-[34%]" />
                <th className="pb-2 text-left font-semibold">{data.a.name}</th>
                <th className="pb-2 text-left font-semibold">{data.b.name}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60 align-top">
              {data.rows.map((r) => (
                <tr key={r.key}>
                  <th scope="row" className="py-2.5 pr-2 text-left font-normal text-[13px] text-foreground/80">{r.label}</th>
                  {[data.a, data.b].map((side) => {
                    const cell = side.rows[r.key];
                    return (
                      <td key={side.symbol} className="py-2.5 pr-2">
                        {cell ? (
                          <>
                            <span className="text-foreground">{cell.value}</span>
                            <span className="block text-[11px] leading-snug text-muted-foreground">{cell.as_of}</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">{data.missing}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {data.story && <p className="mt-5 font-display text-[17px] leading-relaxed text-foreground/90"><Explained text={data.story} /></p>}
          <IdeaBox idea={data.idea} known={null} />
        </>
      )}
    </div>
  );
}

export default function WalkthroughOverlay({ w, initial, onClose, onScreen }: {
  w: Walkthrough; initial: Screen; onClose: () => void; onScreen: (s: Screen) => void;
}) {
  const [screen, setScreen] = useState<Screen>(initial);
  const learnedAtOpen = useRef<Learned>(readLearned());           // "The idea" stays whole for concepts first learned on this walk
  // the walkthroughs of stocks a concept was learned on, for the line comparing them with this one (from the API, never stored here)
  const [others, setOthers] = useState<Record<string, Walkthrough | null>>({});
  useEffect(() => {
    const syms = [...new Set(Object.values(learnedAtOpen.current).map((l) => l.symbol))].filter((s) => s !== w.symbol);
    let live = true;
    Promise.all(syms.map((s) => fetchWalkthrough(s).then((r) => [s, r] as const))).then((pairs) => {
      if (live) setOthers(Object.fromEntries(pairs));
    });
    return () => { live = false; };
  }, [w.symbol]);
  const scroller = useRef<HTMLDivElement>(null);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const total = w.steps.length;

  const go = useCallback((s: Screen) => {
    setScreen((cur) => {
      if (cur.kind === "step") {
        const idea = w.steps[cur.i]?.idea;
        if (idea && w.steps[cur.i].status !== "absent") learn(idea.concept, w.symbol, w.name, new Date(), w.steps[cur.i].check?.same_answer);
      }
      return s;
    });
    onScreen(s);
    scroller.current?.scrollTo({ top: 0 });
  }, [w, onScreen]);

  const next = useCallback(() => {
    if (screen.kind === "step") go(screen.i + 1 < total ? { kind: "step", i: screen.i + 1 } : { kind: "summary" });
  }, [screen, total, go]);
  const back = useCallback(() => {
    if (screen.kind === "step" && screen.i > 0) go({ kind: "step", i: screen.i - 1 });
    else if (screen.kind === "summary") go({ kind: "step", i: total - 1 });
    else if (screen.kind === "compare") go({ kind: "summary" });
  }, [screen, total, go]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [next, back, onClose]);

  const onAsk = () => {
    onClose();
    setTimeout(() => {
      const box = document.getElementById("ask-ivy");
      box?.scrollIntoView({ behavior: "smooth", block: "center" });
      (box as HTMLInputElement | null)?.focus({ preventScroll: true });
    }, 50);
  };

  const step = screen.kind === "step" ? w.steps[screen.i] : null;
  return (
    <div className="fixed inset-0 z-[60] flex items-stretch justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={`${T.ivy}, ${w.name}`}>
      <div className="absolute inset-0 bg-black/75 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <div
        data-walk-card className="relative flex w-full flex-col bg-card sm:my-6 sm:max-h-[min(860px,calc(100svh-48px))] sm:max-w-[620px] sm:rounded-2xl sm:border sm:border-border sm:shadow-2xl"
        onTouchStart={(e) => { touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; }}
        onTouchEnd={(e) => {
          const t0 = touch.current;
          touch.current = null;
          if (!t0) return;
          const dx = e.changedTouches[0].clientX - t0.x, dy = e.changedTouches[0].clientY - t0.y;
          if (Math.abs(dx) > 60 && Math.abs(dx) > 1.5 * Math.abs(dy)) (dx < 0 ? next : back)();
        }}
      >
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 sm:px-6 py-3">
          <div className="flex items-baseline gap-3 min-w-0">
            <span className="font-display text-base font-semibold text-primary">{T.ivy}</span>
            <span className="truncate text-xs text-muted-foreground">
              {w.name}{step ? ` · ${T.stepOf(step.n, total)}` : ""}
            </span>
          </div>
          <button type="button" onClick={onClose} className="tap -mr-2 rounded-lg px-2 py-1 text-sm text-muted-foreground hover:text-foreground" aria-label={T.close}>
            ✕
          </button>
        </header>
        <div className="flex gap-1 px-4 sm:px-6 pt-3" aria-hidden="true">
          {w.steps.map((s, i) => (
            <span key={s.key} className={`h-1 flex-1 rounded-full ${
              screen.kind !== "step" || i < screen.i ? "bg-primary/70" : i === screen.i ? "bg-primary" : "bg-border"}`} />
          ))}
        </div>
        <div ref={scroller} data-walk-scroll className="flex-1 overflow-y-auto overscroll-contain px-4 sm:px-6 pt-5 pb-6">
          {step && <StepScreen key={step.key} step={step} w={w} learned={learnedAtOpen.current} others={others} />}
          {screen.kind === "summary" && <SummaryScreen w={w} onCompare={() => go({ kind: "compare", with: w.compare_choices[0]?.symbol ?? null })} onAsk={onAsk} onClose={onClose} />}
          {screen.kind === "compare" && <CompareScreen w={w} other={screen.with} setOther={(s) => go({ kind: "compare", with: s })} />}
        </div>
        <footer className="flex items-center justify-between gap-3 border-t border-border px-4 sm:px-6 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <button type="button" onClick={back} disabled={screen.kind === "step" && screen.i === 0}
            className="tap rounded-xl px-4 py-2.5 text-sm font-medium text-foreground/85 hover:text-foreground disabled:opacity-30">
            {screen.kind === "compare" ? T.backToSummary : T.back}
          </button>
          {screen.kind === "step" && (
            <button type="button" onClick={next} className="tap rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90">
              {screen.i + 1 < total ? T.next : T.toSummary}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
