"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type Ticker,
  type TickerQuote,
  type ThesisDraftRead,
  type ThesisCreate,
  type Thesis,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown } from "lucide-react";

// ── Step header ────────────────────────────────────────────────────────────────

function StepHeader({ n, label, done }: { n: number; label: string; done?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={cn(
          "w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-colors",
          done ? "bg-emerald-500 text-white" : "bg-muted text-muted-foreground",
        )}
      >
        {done ? "✓" : n}
      </div>
      <h2 className="text-base font-semibold">{label}</h2>
    </div>
  );
}

// ── Ticker typeahead picker ────────────────────────────────────────────────────

function TickerPicker({ tickers, onSelect }: { tickers: Ticker[]; onSelect: (t: Ticker) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return tickers
      .filter(
        (t) =>
          t.symbol.toLowerCase().includes(q) ||
          (t.name ?? "").toLowerCase().includes(q),
      )
      .sort((a, b) => {
        // Exact symbol match first, then starts-with, then by market cap
        const q2 = query.toUpperCase();
        if (a.symbol === q2 && b.symbol !== q2) return -1;
        if (b.symbol === q2 && a.symbol !== q2) return 1;
        const aStarts = a.symbol.startsWith(q2);
        const bStarts = b.symbol.startsWith(q2);
        if (aStarts && !bStarts) return -1;
        if (!aStarts && bStarts) return 1;
        return (b.market_cap ?? 0) - (a.market_cap ?? 0);
      })
      .slice(0, 8);
  }, [tickers, query]);

  function handleSelect(t: Ticker) {
    onSelect(t);
    setQuery("");
    setOpen(false);
  }

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <input
        ref={inputRef}
        type="search"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        placeholder="Type a symbol or company name — e.g. AAPL, Microsoft…"
        className="w-full h-12 rounded-xl border bg-background px-4 text-base placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
      />
      {open && query.trim() && matches.length > 0 && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 rounded-xl border bg-popover shadow-lg overflow-hidden">
          {matches.map((t) => (
            <button
              key={t.id}
              type="button"
              onMouseDown={(e) => { e.preventDefault(); handleSelect(t); }}
              className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent transition-colors"
            >
              <span className="font-bold text-sm w-14 shrink-0 tabular-nums">{t.symbol}</span>
              <span className="text-sm text-muted-foreground flex-1 truncate">{t.name}</span>
              {t.sector && (
                <span className="text-xs text-muted-foreground/70 shrink-0 hidden sm:block">{t.sector}</span>
              )}
            </button>
          ))}
        </div>
      )}
      {open && query.trim() && matches.length === 0 && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 rounded-xl border bg-popover shadow-lg px-4 py-3 text-sm text-muted-foreground">
          No tickers match &ldquo;{query}&rdquo;
        </div>
      )}
    </div>
  );
}

// ── Draft display ──────────────────────────────────────────────────────────────

interface OptionLegDraft {
  option_type: "call" | "put";
  strike: number | null;
  strike2: number | null;
  option_expiration: string | null;
  spread_type: string | null;
}

function DraftDisplay({
  draft,
  onAccept,
  onRegenerate,
}: {
  draft: ThesisDraftRead;
  onAccept: (target: number | null, reasoning: string, leg: OptionLegDraft | null) => void;
  onRegenerate: () => void;
}) {
  const fb = draft.fact_block;

  function handleAccept() {
    const hasStrike = draft.suggested_strike != null;
    const hasSpread = draft.suggested_spread_strike != null;
    const leg: OptionLegDraft | null = hasStrike
      ? {
          option_type: draft.direction === "bullish" ? "call" : "put",
          strike: draft.suggested_strike,
          strike2: draft.suggested_spread_strike,
          option_expiration: fb.expiration_used ?? null,
          spread_type: hasSpread
            ? draft.direction === "bullish"
              ? "bull_call_spread"
              : "bear_put_spread"
            : null,
        }
      : null;
    onAccept(draft.suggested_target, draft.reasoning, leg);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          AI Draft — {draft.aggressiveness} · {draft.direction}
        </p>
        <span className="text-xs text-muted-foreground">{draft.model_used}</span>
      </div>

      {draft.realism_flag && (
        <div className="rounded-lg bg-amber-50 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 px-4 py-3">
          <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-1">⚠ Realism Flag</p>
          <p className="text-sm text-amber-800 dark:text-amber-300">{draft.realism_flag}</p>
        </div>
      )}

      <div className="space-y-2">
        {draft.strategy && (
          <p className="text-lg font-semibold">{draft.strategy}</p>
        )}
        <div className="flex gap-6 flex-wrap text-sm text-muted-foreground">
          {draft.suggested_target != null && (
            <span>
              Target:{" "}
              <span className="text-foreground font-medium">${draft.suggested_target.toFixed(2)}</span>
            </span>
          )}
          {draft.suggested_strike != null && (
            <span>
              Strike:{" "}
              <span className="text-foreground font-medium">${draft.suggested_strike.toFixed(2)}</span>
            </span>
          )}
          {draft.suggested_spread_strike != null && (
            <span>
              Spread leg:{" "}
              <span className="text-foreground font-medium">${draft.suggested_spread_strike.toFixed(2)}</span>
            </span>
          )}
        </div>
      </div>

      <p className="text-muted-foreground leading-relaxed">{draft.reasoning}</p>

      <div className="rounded-lg bg-muted/40 px-4 py-3 grid grid-cols-2 gap-x-8 gap-y-1.5 text-xs text-muted-foreground">
        <span>Price: <span className="text-foreground">${fb.current_price.toFixed(2)}</span></span>
        <span>
          Implied move:{" "}
          <span className="text-foreground">
            ±{fb.expected_move_pct?.toFixed(1) ?? "—"}% (±${fb.expected_move_dollars?.toFixed(2) ?? "—"})
          </span>
        </span>
        <span>
          Range:{" "}
          <span className="text-foreground">
            ${fb.implied_range_low?.toFixed(2) ?? "—"} – ${fb.implied_range_high?.toFixed(2) ?? "—"}
          </span>
        </span>
        <span>Earnings: <span className="text-foreground">{fb.earnings_date ?? "—"}</span></span>
        <span>
          Hist avg ±:{" "}
          <span className="text-foreground">{fb.hist_avg_abs_move_pct?.toFixed(2) ?? "—"}%</span>
        </span>
        <span>Beat rate: <span className="text-foreground">{fb.beat_rate_pct?.toFixed(0) ?? "—"}%</span></span>
        <span>ATM IV: <span className="text-foreground">{fb.atm_iv_pct?.toFixed(1) ?? "—"}%</span></span>
        <span>RV rank: <span className="text-foreground">{fb.rv_rank?.toFixed(0) ?? "—"}/100</span></span>
      </div>

      <p className="text-xs text-muted-foreground italic">
        Data-grounded suggestion — not a recommendation. Review carefully before saving.
      </p>

      <div className="flex gap-3 pt-1">
        <button
          type="button"
          onClick={handleAccept}
          className="rounded-lg bg-primary text-primary-foreground px-6 py-2.5 text-sm font-semibold hover:bg-primary/90 transition-colors"
        >
          Continue with this trade →
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="rounded-lg border bg-background px-4 py-2.5 text-sm hover:bg-accent transition-colors"
        >
          Regenerate
        </button>
      </div>
    </div>
  );
}

// ── Conviction picker ──────────────────────────────────────────────────────────

function ConvictionPicker({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex gap-2">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          className={cn(
            "w-9 h-9 rounded-lg border-2 text-sm font-bold transition-all",
            value === n
              ? "bg-blue-500 border-blue-500 text-white"
              : "border-border text-muted-foreground hover:border-blue-300 hover:text-foreground",
          )}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

type BuildStep =
  | "pick_stock"
  | "pick_direction"
  | "generating"
  | "review_draft"
  | "confirm"
  | "saving"
  | "done";

export default function BuildTradePage() {
  // Ticker list
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [tickersLoading, setTickersLoading] = useState(true);

  // Flow state
  const [step, setStep] = useState<BuildStep>("pick_stock");

  // Step 1 — stock
  const [selectedTicker, setSelectedTicker] = useState<Ticker | null>(null);
  const [quote, setQuote] = useState<TickerQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);

  // Step 2 — direction
  const [direction, setDirection] = useState<"bullish" | "bearish" | null>(null);
  const [aggressiveness, setAggressiveness] = useState<"conservative" | "moderate" | "aggressive">("moderate");

  // Step 3 — draft
  const [draft, setDraft] = useState<ThesisDraftRead | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);

  // Step 4 — confirm
  const defaultTargetDate = () => {
    const d = new Date();
    d.setMonth(d.getMonth() + 3);
    return d.toISOString().slice(0, 10);
  };
  const [conviction, setConviction] = useState(3);
  const [targetDate, setTargetDate] = useState(defaultTargetDate);
  const [priceTarget, setPriceTarget] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [optionLeg, setOptionLeg] = useState<OptionLegDraft | null>(null);
  const [contracts, setContracts] = useState("1");
  const [saveError, setSaveError] = useState<string | null>(null);

  // Result
  const [savedThesis, setSavedThesis] = useState<Thesis | null>(null);

  useEffect(() => {
    api.tickers.list().then(setTickers).catch(() => null).finally(() => setTickersLoading(false));
  }, []);

  function handleSelectTicker(t: Ticker) {
    setSelectedTicker(t);
    setQuote(null);
    setQuoteLoading(true);
    setStep("pick_direction");
    api.tickers
      .quote(t.symbol)
      .then(setQuote)
      .catch(() => null)
      .finally(() => setQuoteLoading(false));
  }

  function handleChangeTicker() {
    setSelectedTicker(null);
    setQuote(null);
    setDirection(null);
    setDraft(null);
    setDraftError(null);
    setStep("pick_stock");
  }

  function pickDirection(d: "bullish" | "bearish") {
    setDirection(d);
    // Reset draft if user changes direction after seeing it
    if (step === "review_draft" || step === "confirm") {
      setStep("pick_direction");
      setDraft(null);
    }
  }

  async function handleGenerate() {
    if (!selectedTicker || !direction) return;
    setStep("generating");
    setDraftError(null);
    try {
      const d = await api.theses.draft({ symbol: selectedTicker.symbol, direction, aggressiveness });
      setDraft(d);
      setStep("review_draft");
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : "Generation failed — please try again");
      setStep("pick_direction");
    }
  }

  function handleAcceptDraft(target: number | null, draftReasoning: string, leg: OptionLegDraft | null) {
    if (target != null) setPriceTarget(target.toFixed(2));
    setReasoning(draftReasoning);
    setOptionLeg(leg);
    setStep("confirm");
  }

  async function handleSave() {
    if (!selectedTicker || !direction) return;
    setStep("saving");
    setSaveError(null);
    try {
      const optionPayload: Partial<ThesisCreate> =
        optionLeg?.strike != null && optionLeg.option_expiration
          ? {
              option_type: optionLeg.option_type,
              strike: optionLeg.strike,
              option_expiration: optionLeg.option_expiration,
              contracts: parseInt(contracts) || 1,
              ...(optionLeg.strike2 != null ? { strike2: optionLeg.strike2 } : {}),
              ...(optionLeg.spread_type ? { spread_type: optionLeg.spread_type } : {}),
            }
          : {};
      const thesis = await api.theses.create({
        symbol: selectedTicker.symbol,
        direction,
        conviction,
        target_date: targetDate,
        ...(priceTarget ? { price_target: parseFloat(priceTarget) } : {}),
        ...(reasoning.trim() ? { reasoning: reasoning.trim() } : {}),
        from_ai_draft: true,
        ...optionPayload,
      });
      setSavedThesis(thesis);
      setStep("done");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed — please try again");
      setStep("confirm");
    }
  }

  function handleBuildAnother() {
    setStep("pick_stock");
    setSelectedTicker(null);
    setQuote(null);
    setDirection(null);
    setDraft(null);
    setDraftError(null);
    setConviction(3);
    setTargetDate(defaultTargetDate());
    setPriceTarget("");
    setReasoning("");
    setOptionLeg(null);
    setContracts("1");
    setSaveError(null);
    setSavedThesis(null);
  }

  const currentPrice = quote?.price ?? null;

  // ── Done ────────────────────────────────────────────────────────────────────

  if (step === "done" && savedThesis) {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-2xl mx-auto">
          <div className="mb-8">
            <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
              ← Home
            </Link>
          </div>
          <div className="rounded-2xl border bg-card px-8 py-12 text-center space-y-5">
            <div className="text-5xl">✓</div>
            <h2 className="text-2xl font-bold">Trade thesis saved</h2>
            <p className="text-muted-foreground text-sm max-w-sm mx-auto leading-relaxed">
              {direction === "bullish" ? "Bullish" : "Bearish"} thesis on{" "}
              <span className="font-semibold text-foreground">{selectedTicker?.symbol}</span>{" "}
              has been added to your tracker.
              {optionLeg?.strike != null && (
                <>
                  {" "}Option leg:{" "}
                  {optionLeg.option_type === "call" ? "Long call" : "Long put"}{" "}
                  ${optionLeg.strike.toFixed(0)}
                  {optionLeg.strike2 != null ? ` / $${optionLeg.strike2.toFixed(0)}` : ""}{" "}
                  · {optionLeg.option_expiration}.
                  {" "}Entry premium captured live.
                </>
              )}
            </p>
            <div className="flex justify-center gap-4 pt-2">
              <Link
                href="/theses"
                className="rounded-xl bg-primary text-primary-foreground px-8 py-3 text-sm font-semibold hover:bg-primary/90 transition-colors"
              >
                View in tracker →
              </Link>
              <button
                type="button"
                onClick={handleBuildAnother}
                className="rounded-xl border bg-background px-8 py-3 text-sm font-semibold hover:bg-accent transition-colors"
              >
                Build another
              </button>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // ── Flow steps ───────────────────────────────────────────────────────────────

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-2xl mx-auto">

        {/* Page header */}
        <div className="mb-10">
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground mb-5 inline-block">
            ← Home
          </Link>
          <h1 className="text-3xl font-bold tracking-tight">Build a Trade</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            AI-drafted idea grounded in live options data, earnings history, and volatility.
            Not financial advice.
          </p>
        </div>

        <div className="space-y-10">

          {/* ── Step 1: Pick stock ─────────────────────────────────────────────── */}
          <section className="space-y-4">
            <StepHeader n={1} label="Pick a stock" done={!!selectedTicker} />

            {!selectedTicker ? (
              tickersLoading ? (
                <div className="h-12 bg-muted rounded-xl animate-pulse" />
              ) : (
                <TickerPicker tickers={tickers} onSelect={handleSelectTicker} />
              )
            ) : (
              <div className="flex items-center justify-between rounded-xl border bg-card px-5 py-3.5">
                <div className="flex items-center gap-4 min-w-0">
                  <span className="text-2xl font-bold tracking-tight">{selectedTicker.symbol}</span>
                  {selectedTicker.name && (
                    <span className="text-sm text-muted-foreground truncate hidden sm:block">
                      {selectedTicker.name}
                    </span>
                  )}
                  <span className="text-sm font-semibold tabular-nums shrink-0">
                    {quoteLoading ? (
                      <span className="inline-block w-14 h-4 bg-muted rounded animate-pulse align-middle" />
                    ) : currentPrice != null ? (
                      `$${currentPrice.toFixed(2)}`
                    ) : (
                      ""
                    )}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleChangeTicker}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors ml-4 shrink-0"
                >
                  Change
                </button>
              </div>
            )}
          </section>

          {/* ── Step 2: Direction ─────────────────────────────────────────────── */}
          {selectedTicker && (
            <section className="space-y-4">
              <StepHeader n={2} label="Pick a direction" done={!!direction && step !== "pick_direction"} />

              <div className="grid grid-cols-2 gap-4">
                <button
                  type="button"
                  onClick={() => pickDirection("bullish")}
                  className={cn(
                    "py-8 rounded-2xl border-2 text-center transition-all select-none",
                    direction === "bullish"
                      ? "bg-emerald-50 border-emerald-500 text-emerald-700 dark:bg-emerald-900/30 dark:border-emerald-400 dark:text-emerald-300"
                      : "border-border hover:border-emerald-300 hover:bg-emerald-50/40 dark:hover:border-emerald-700 dark:hover:bg-emerald-900/10",
                  )}
                >
                  <TrendingUp aria-hidden="true" className="w-9 h-9 mx-auto mb-2" strokeWidth={1.75} />
                  <div className="text-base font-bold">Bullish</div>
                  <div className="text-xs opacity-60 mt-1">expecting it to rise</div>
                </button>

                <button
                  type="button"
                  onClick={() => pickDirection("bearish")}
                  className={cn(
                    "py-8 rounded-2xl border-2 text-center transition-all select-none",
                    direction === "bearish"
                      ? "bg-red-50 border-red-500 text-red-700 dark:bg-red-900/30 dark:border-red-400 dark:text-red-300"
                      : "border-border hover:border-red-300 hover:bg-red-50/40 dark:hover:border-red-700 dark:hover:bg-red-900/10",
                  )}
                >
                  <TrendingDown aria-hidden="true" className="w-9 h-9 mx-auto mb-2" strokeWidth={1.75} />
                  <div className="text-base font-bold">Bearish</div>
                  <div className="text-xs opacity-60 mt-1">expecting it to fall</div>
                </button>
              </div>

              {/* Aggressiveness + generate */}
              {direction && (step === "pick_direction" || step === "generating") && (
                <div className="flex items-center gap-4 flex-wrap pt-1">
                  <div className="flex gap-1.5">
                    {(["conservative", "moderate", "aggressive"] as const).map((a) => (
                      <button
                        key={a}
                        type="button"
                        onClick={() => setAggressiveness(a)}
                        className={cn(
                          "px-3.5 py-1.5 rounded-lg text-sm capitalize transition-colors",
                          aggressiveness === a
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-muted-foreground hover:bg-accent",
                        )}
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={handleGenerate}
                    disabled={step === "generating"}
                    className="rounded-lg bg-primary text-primary-foreground px-6 py-2 text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-60"
                  >
                    {step === "generating" ? "Generating…" : "Generate trade →"}
                  </button>
                </div>
              )}

              {draftError && (
                <p className="text-sm text-red-500">{draftError}</p>
              )}
            </section>
          )}

          {/* ── Step 3: Review draft ──────────────────────────────────────────── */}
          {step === "review_draft" && draft && (
            <section className="space-y-4">
              <StepHeader n={3} label="Review the suggestion" />
              <div className="rounded-2xl border bg-card px-6 py-6">
                <DraftDisplay
                  draft={draft}
                  onAccept={handleAcceptDraft}
                  onRegenerate={() => { setStep("pick_direction"); setDraft(null); }}
                />
              </div>
            </section>
          )}
          {(step === "confirm" || step === "saving") && draft && (
            <section className="space-y-4">
              <StepHeader n={3} label="Review the suggestion" done />
              <div className="rounded-2xl border bg-muted/30 px-4 py-3 text-sm text-muted-foreground flex items-center gap-2">
                <span className="font-medium text-foreground">{draft.strategy}</span>
                {optionLeg?.strike != null && (
                  <span>· {optionLeg.option_type} ${optionLeg.strike.toFixed(0)}{optionLeg.strike2 != null ? `/$${optionLeg.strike2.toFixed(0)}` : ""} exp {optionLeg.option_expiration}</span>
                )}
                <button onClick={() => setStep("review_draft")} className="ml-auto text-xs underline hover:text-foreground">
                  Edit
                </button>
              </div>
            </section>
          )}

          {/* ── Step 4: Confirm ───────────────────────────────────────────────── */}
          {(step === "confirm" || step === "saving") && (
            <section className="space-y-4">
              <StepHeader n={4} label="Confirm &amp; save" />
              <div className="rounded-2xl border bg-card px-6 py-6 space-y-5">

                <div className="grid grid-cols-2 gap-5">
                  <div>
                    <label className="block text-xs font-medium text-muted-foreground mb-2">
                      Conviction
                    </label>
                    <ConvictionPicker value={conviction} onChange={setConviction} />
                    <p className="text-xs text-muted-foreground mt-1">1 = tentative · 5 = high conviction</p>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-muted-foreground mb-2">
                      Target date
                    </label>
                    <input
                      type="date"
                      value={targetDate}
                      onChange={(e) => setTargetDate(e.target.value)}
                      className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-muted-foreground mb-2">
                      Price target <span className="font-normal opacity-60">(optional)</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={priceTarget}
                      onChange={(e) => setPriceTarget(e.target.value)}
                      placeholder="—"
                      className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
                    />
                  </div>
                  {optionLeg?.strike != null && (
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-2">
                        Contracts
                      </label>
                      <input
                        type="number"
                        min={1}
                        value={contracts}
                        onChange={(e) => setContracts(e.target.value)}
                        className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
                      />
                    </div>
                  )}
                </div>

                {optionLeg?.strike != null && (
                  <div className="rounded-lg bg-muted/40 px-4 py-2.5 text-xs text-muted-foreground">
                    Option leg:{" "}
                    <span className="text-foreground font-medium">
                      {optionLeg.option_type === "call" ? "Long call" : "Long put"}{" "}
                      ${optionLeg.strike.toFixed(0)}
                      {optionLeg.strike2 != null ? ` / $${optionLeg.strike2.toFixed(0)}` : ""}
                      {optionLeg.option_expiration ? ` · exp ${optionLeg.option_expiration}` : ""}
                      {optionLeg.spread_type ? ` (${optionLeg.spread_type.replace(/_/g, " ")})` : ""}
                    </span>
                    {" · Entry premium captured live at save."}
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-2">
                    Reasoning
                  </label>
                  <textarea
                    rows={4}
                    value={reasoning}
                    onChange={(e) => setReasoning(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm resize-none"
                  />
                </div>

                {saveError && <p className="text-sm text-red-500">{saveError}</p>}

                <div className="flex gap-3 pt-1">
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={step === "saving"}
                    className="rounded-xl bg-primary text-primary-foreground px-8 py-2.5 text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-60"
                  >
                    {step === "saving" ? "Saving…" : "Save thesis →"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setStep("review_draft")}
                    disabled={step === "saving"}
                    className="rounded-xl border bg-background px-5 py-2.5 text-sm hover:bg-accent transition-colors disabled:opacity-50"
                  >
                    ← Back
                  </button>
                </div>
              </div>
            </section>
          )}

        </div>
      </div>
    </main>
  );
}
