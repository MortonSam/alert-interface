"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  api,
  type AlertPickRead,
  type Ticker,
  type TickerQuote,
  type ThesisDraftRead,
  type ThesisDraftAlternativeRead,
  type ThesisCreate,
  type Thesis,
} from "@/lib/api";
import { cn, rvRankShort } from "@/lib/utils";
import { buildPlainEnglish } from "@/lib/plain-english";
import Callout from "@/components/Callout";
import { GiBull, GiBearFace } from "react-icons/gi";
import { HiSparkles } from "react-icons/hi2";
import PayoffSimulator from "@/components/PayoffSimulator";
import { type Leg, dateMs } from "@/lib/black-scholes";

// ── Recent tickers (localStorage, SSR-safe) ──────────────────────────────────

type RecentTicker = { symbol: string; name: string | null };
const RECENT_KEY = "alertinterface:recent_tickers";

function readRecents(): RecentTicker[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.slice(0, 5) : [];
  } catch { return []; }
}

function pushRecent(t: { symbol: string; name: string | null }) {
  try {
    const list = readRecents().filter((r) => r.symbol !== t.symbol);
    list.unshift({ symbol: t.symbol, name: t.name });
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 5)));
  } catch { /* quota / private browsing — ignore */ }
}

// ── Step header ────────────────────────────────────────────────────────────────

function StepHeader({ n, label, done }: { n: number; label: string; done?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={cn(
          "w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-colors",
          done ? "bg-success text-success-foreground" : "bg-muted text-muted-foreground",
        )}
      >
        {done ? "✓" : n}
      </div>
      <h2 className="text-base font-semibold text-muted-foreground">{label}</h2>
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

// ── Draft simulator props builder ─────────────────────────────────────────────

function buildDraftSimProps(draft: ThesisDraftRead) {
  const fb = draft.fact_block;
  if (draft.suggested_strike == null) return null;
  if (draft.direction !== "bullish" && draft.direction !== "bearish") return null;
  if (fb.expiration_used == null) return null;
  const kind: "call" | "put" = draft.direction === "bullish" ? "call" : "put";

  const findRow = (k: number) =>
    fb.primary_strikes.find(r => Math.abs(r.strike - k) < 1e-3)
    ?? fb.secondary_strikes.find(r => Math.abs(r.strike - k) < 1e-3);

  const row1 = findRow(draft.suggested_strike);
  if (!row1) return null;
  let usingIVFallback = row1.iv == null;
  const legs: Leg[] = [{
    kind, K: draft.suggested_strike, mid: row1.mid,
    sigma: (row1.iv ?? fb.atm_iv_pct ?? 30) / 100,
    dir: 1, label: `Long $${draft.suggested_strike}`,
  }];

  if (draft.suggested_spread_strike != null) {
    const row2 = findRow(draft.suggested_spread_strike);
    if (!row2) return null;
    usingIVFallback = usingIVFallback || row2.iv == null;
    legs.push({
      kind, K: draft.suggested_spread_strike, mid: row2.mid,
      sigma: (row2.iv ?? fb.atm_iv_pct ?? 30) / 100,
      dir: -1, label: `Short $${draft.suggested_spread_strike}`,
    });
  }

  return {
    legs,
    spot: fb.current_price,
    currentPrice: fb.current_price,
    symbol: draft.symbol,
    expirationMs: dateMs(fb.expiration_used),
    mult: 100,
    xMin: fb.implied_range_low ?? fb.current_price * 0.8,
    xMax: fb.implied_range_high ?? fb.current_price * 1.2,
    earningsMs: fb.earnings_date ? dateMs(fb.earnings_date) : null,
    usingIVFallback,
    sdFailed: false,
  };
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

  // ── Cost / risk — computed from structured primary_strikes, never from prose ─
  const isSpread = draft.suggested_spread_strike != null;
  const shortName = isSpread
    ? (draft.direction === "bullish" ? "Bull call spread" : "Bear put spread")
    : `Long ${draft.direction === "bullish" ? "call" : "put"}`;
  const leg1Mid: number | null = draft.suggested_strike != null
    ? (fb.primary_strikes.find((r) => r.strike === draft.suggested_strike)?.mid ?? null)
    : null;
  const leg2Mid: number | null = draft.suggested_spread_strike != null
    ? (fb.primary_strikes.find((r) => r.strike === draft.suggested_spread_strike)?.mid ?? null)
    : null;
  const netDebit: number | null =
    isSpread && leg1Mid != null && leg2Mid != null ? leg1Mid - leg2Mid : null;
  const spreadWidth: number | null =
    draft.suggested_strike != null && draft.suggested_spread_strike != null
      ? Math.abs(draft.suggested_spread_strike - draft.suggested_strike)
      : null;
  // Single leg: cost = premium × 100. Spread: cost = net debit × 100.
  const costPerContract: number | null = isSpread
    ? (netDebit != null ? netDebit * 100 : null)
    : (leg1Mid != null ? leg1Mid * 100 : null);
  const maxLossPerContract: number | null = costPerContract; // identical for both structures
  // Spread max gain = (width − net debit) × 100. Long put = (strike − premium) × 100.
  // Long call max gain is unlimited — handled in JSX.
  const maxGainPerContract: number | null = isSpread
    ? (spreadWidth != null && netDebit != null ? (spreadWidth - netDebit) * 100 : null)
    : draft.direction === "bearish" && draft.suggested_strike != null && leg1Mid != null
      ? (draft.suggested_strike - leg1Mid) * 100
      : null;

  // Breakeven — derived from already-computed mids, never re-looked-up
  // Bull call spread: long call strike + net debit (breakeven above long leg)
  // Bear put spread:  long put strike − net debit (breakeven below long leg)
  const breakeven: number | null = (() => {
    if (draft.suggested_strike == null) return null;
    if (isSpread) {
      if (netDebit == null) return null;
      return draft.direction === "bullish"
        ? draft.suggested_strike + netDebit
        : draft.suggested_strike - netDebit;
    }
    if (leg1Mid == null) return null;
    return draft.direction === "bullish"
      ? draft.suggested_strike + leg1Mid
      : draft.suggested_strike - leg1Mid;
  })();

  // Plain-English reasoning (deterministic, template-stitched)
  const plainEnglish = buildPlainEnglish({
    shortName,
    direction: draft.direction,
    isSpread,
    symbol: draft.symbol,
    strike: draft.suggested_strike,
    spreadStrike: draft.suggested_spread_strike,
    cost: costPerContract,
    maxLoss: maxLossPerContract,
    maxGain: (!isSpread && draft.direction === "bullish") ? "unlimited" : maxGainPerContract,
    netDebit,
    breakeven,
    expiration: fb.expiration_used ?? null,
  });

  const [reasoningMode, setReasoningMode] = useState<"plain" | "detailed">("plain");

  // ── Budget alternative — local state, on-demand only ─────────────────────
  const [altOpen, setAltOpen] = useState(false);
  const [altBudgetInput, setAltBudgetInput] = useState("");
  const [altLoading, setAltLoading] = useState(false);
  const [altResult, setAltResult] = useState<ThesisDraftAlternativeRead | null>(null);
  const [altError, setAltError] = useState(false);

  const altBudgetParsed = parseFloat(altBudgetInput);
  const altBudgetValid =
    altBudgetInput.trim() !== "" && Number.isFinite(altBudgetParsed) && altBudgetParsed > 0;

  // ── Alternative cost/risk — derived from altResult when fits=true ──────────
  const altIsSpread = altResult?.fits ? altResult.suggested_spread_strike != null : false;
  const altCostToEnter: number | null = altResult?.fits ? (altResult.cost_to_enter ?? null) : null;
  const altMaxLoss: number | null = altCostToEnter;
  // Spread: (width − net_debit) × 100 = width × 100 − cost_to_enter
  // Naked call: Unlimited (signal via altIsUnlimited)
  // Naked put: (strike − cost_to_enter/100) × 100
  const altIsUnlimited = altResult?.fits === true && !altIsSpread && draft.direction === "bullish";
  const altMaxGain: number | null =
    altResult?.fits
      ? (altIsSpread && altCostToEnter != null && altResult.suggested_strike != null && altResult.suggested_spread_strike != null
          ? Math.abs(altResult.suggested_spread_strike - altResult.suggested_strike) * 100 - altCostToEnter
          : (!altIsSpread && draft.direction === "bearish" && altResult.suggested_strike != null && altCostToEnter != null
              ? (altResult.suggested_strike - altCostToEnter / 100) * 100
              : null))
      : null;

  const simProps = useMemo(() => buildDraftSimProps(draft), [draft]);

  function resetAlt() {
    setAltOpen(false);
    setAltBudgetInput("");
    setAltResult(null);
    setAltError(false);
  }

  async function handleGenerateAlternative() {
    if (!altBudgetValid || costPerContract == null || draft.suggested_strike == null) return;
    setAltLoading(true);
    setAltResult(null);
    setAltError(false);
    try {
      const result = await api.theses.draftAlternative({
        symbol: draft.symbol,
        direction: draft.direction as "bullish" | "bearish",
        aggressiveness: draft.aggressiveness as "conservative" | "moderate" | "aggressive",
        budget: altBudgetParsed,
        best_strike: draft.suggested_strike,
        best_spread_strike: draft.suggested_spread_strike ?? null,
        best_cost: costPerContract,
      });
      setAltResult(result);
    } catch {
      setAltError(true);
    } finally {
      setAltLoading(false);
    }
  }

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

      {/* A) Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          AI Draft — {draft.aggressiveness} · {draft.direction}
        </p>
        <span className="font-mono text-xs text-muted-foreground">{draft.model_used}</span>
      </div>

      {/* B) Realism flag */}
      {draft.realism_flag && (
        <Callout severity="caution" title="Realism Flag">
          {draft.realism_flag}
        </Callout>
      )}

      {/* C) Headline — strategy name + strikes + expiration in font-mono */}
      <div className="space-y-1.5">
        <h2 className="text-3xl md:text-4xl font-display font-bold tracking-tight">
          {shortName}
          {draft.suggested_strike != null && (
            <span className="font-mono text-foreground">
              {" "}${draft.suggested_strike}
              {draft.suggested_spread_strike != null && ` / $${draft.suggested_spread_strike}`}
            </span>
          )}
          {fb.expiration_used && (
            <span className="font-mono text-foreground">
              {" "}· {new Date(fb.expiration_used + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
            </span>
          )}
        </h2>

        {/* D) Subline — target, muted label, mono value */}
        <div className="flex gap-6 flex-wrap text-sm text-muted-foreground">
          {draft.suggested_target != null && (
            <span>
              Target{" "}
              <span className="font-mono text-foreground">${draft.suggested_target.toFixed(2)}</span>
            </span>
          )}
        </div>

        {/* E) Leg detail — verbose strategy name, muted */}
        {draft.strategy && (
          <p className="font-mono text-sm text-muted-foreground">{draft.strategy}</p>
        )}
      </div>

      {/* F) Reasoning — with Plain English / Detailed toggle */}
      <div className="space-y-2">
        {plainEnglish != null && (
          <div className="inline-flex rounded-lg border border-border bg-secondary p-0.5 text-xs font-medium">
            {(["plain", "detailed"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setReasoningMode(mode)}
                className={cn(
                  "rounded-md px-3 py-1.5 transition-colors",
                  reasoningMode === mode
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {mode === "plain" ? "Plain English" : "Detailed"}
              </button>
            ))}
          </div>
        )}
        <p className="text-muted-foreground leading-relaxed max-w-prose">
          {plainEnglish != null && reasoningMode === "plain" ? plainEnglish : draft.reasoning}
        </p>
      </div>

      {/* G) Fact grid */}
      <div className="bg-secondary border border-border rounded-md p-5 grid grid-cols-1 sm:grid-cols-2 gap-x-10 gap-y-2.5 text-xs text-muted-foreground">
        <span>Price: <span className="font-mono text-foreground">${fb.current_price.toFixed(2)}</span></span>
        <span>
          Implied move:{" "}
          <span className="font-mono text-foreground">
            ±{fb.expected_move_pct?.toFixed(1) ?? "—"}% (±${fb.expected_move_dollars?.toFixed(2) ?? "—"})
          </span>
        </span>
        <span>
          Range:{" "}
          <span className="font-mono text-foreground">
            ${fb.implied_range_low?.toFixed(2) ?? "—"} – ${fb.implied_range_high?.toFixed(2) ?? "—"}
          </span>
        </span>
        <span>Earnings: <span className="font-mono text-foreground">{fb.earnings_date ?? "—"}</span></span>
        <span>
          Hist avg ±:{" "}
          <span className="font-mono text-foreground">{fb.hist_avg_abs_move_pct?.toFixed(2) ?? "—"}%</span>
        </span>
        <span>Beat rate: <span className="font-mono text-foreground">{fb.beat_rate_pct?.toFixed(0) ?? "—"}%</span></span>
        <span>ATM IV: <span className="font-mono text-foreground">{fb.atm_iv_pct?.toFixed(1) ?? "—"}%</span></span>
        <span>Realized-vol rank: {fb.rv_rank != null ? (<><span className="font-mono text-foreground">{fb.rv_rank.toFixed(0)}</span> · <span className={rvRankShort(fb.rv_rank).colorClass}>{rvRankShort(fb.rv_rank).tag}</span></>) : <span className="font-mono text-foreground">—</span>}</span>
        <span>IV−RV spread: <span className="font-mono text-foreground">{fb.iv_rv_spread_pp != null ? `${(fb.iv_rv_spread_pp as number) > 0 ? "+" : ""}${(fb.iv_rv_spread_pp as number).toFixed(1)}pp` : "—"}</span></span>
        {draft.vol_regime && (
          <span>
            Vol regime:{" "}
            <span className={cn(
              "font-mono font-medium",
              draft.vol_regime === "iv_rich" ? "text-amber-600 dark:text-amber-400" :
              draft.vol_regime === "iv_cheap" ? "text-green-600 dark:text-green-400" :
              "text-foreground"
            )}>
              {draft.vol_regime === "iv_rich" ? "IV Rich" :
               draft.vol_regime === "iv_cheap" ? "IV Cheap" : "IV Fair"}
            </span>
          </span>
        )}
      </div>

      {/* H) Position cost & risk */}
      {draft.suggested_strike != null && (
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Position cost &amp; risk · per contract
          </p>
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-secondary border border-border rounded-md p-5">
              <p className="text-xs text-muted-foreground mb-2">Cost to enter</p>
              <p className="font-mono text-3xl font-semibold tabular-nums">
                {costPerContract != null ? `$${Math.round(costPerContract)}` : "—"}
              </p>
            </div>
            <div className="bg-secondary border border-border rounded-md p-5">
              <p className="text-xs text-muted-foreground mb-2">Max loss</p>
              <p className="font-mono text-3xl font-semibold tabular-nums text-destructive">
                {maxLossPerContract != null ? `$${Math.round(maxLossPerContract)}` : "—"}
              </p>
            </div>
            <div className="bg-secondary border border-border rounded-md p-5">
              <p className="text-xs text-muted-foreground mb-2">Max gain</p>
              {isSpread ? (
                <p className="font-mono text-3xl font-semibold tabular-nums text-success">
                  {maxGainPerContract != null ? `$${Math.round(maxGainPerContract).toLocaleString()}` : "—"}
                </p>
              ) : draft.direction === "bullish" ? (
                <p className="text-xl font-semibold text-success">Unlimited</p>
              ) : (
                <p className="font-mono text-3xl font-semibold tabular-nums text-success">
                  {maxGainPerContract != null ? `$${Math.round(maxGainPerContract).toLocaleString()}` : "—"}
                </p>
              )}
            </div>
          </div>
          {isSpread && netDebit != null && spreadWidth != null && (
            <p className="text-xs text-muted-foreground">
              Net debit ${netDebit.toFixed(2)} · spread width ${spreadWidth.toFixed(0)}
            </p>
          )}
          {leg1Mid == null && (
            <Callout severity="caution" compact>
              Cost unavailable — strike not found in current chain data
            </Callout>
          )}
        </div>
      )}

      {/* I) Payoff simulator */}
      {simProps && <PayoffSimulator {...simProps} />}

      {/* J) Budget alternative trigger + panel */}
      {costPerContract != null && (
        <div className="space-y-3">
          {!altOpen ? (
            <button
              type="button"
              onClick={() => setAltOpen(true)}
              className="text-sm font-medium text-cool hover:text-cool/80 transition-colors"
            >
              Too expensive? See an affordable alternative →
            </button>
          ) : (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-muted-foreground shrink-0">Budget ($)</span>
                <input
                  type="number"
                  min={0}
                  step={100}
                  value={altBudgetInput}
                  onChange={(e) => {
                    setAltBudgetInput(e.target.value);
                    setAltResult(null);
                    setAltError(false);
                  }}
                  placeholder="e.g. 2000"
                  className="w-32 rounded-lg border bg-background px-3 py-1.5 text-sm"
                />
                <button
                  type="button"
                  onClick={handleGenerateAlternative}
                  disabled={altLoading || !altBudgetValid}
                  className="rounded-lg border bg-muted text-foreground px-4 py-1.5 text-xs font-medium hover:bg-accent transition-colors disabled:opacity-50"
                >
                  {altLoading ? "Generating…" : "Generate alternative"}
                </button>
                <button
                  type="button"
                  onClick={resetAlt}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>

              {altError && (
                <p className="text-xs text-muted-foreground">
                  Couldn&apos;t generate an alternative — try again.
                </p>
              )}

              {altResult?.fits && (
                <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-4 space-y-2.5">
                  <p className="text-base font-bold text-foreground">
                    Affordable alternative
                    <span className="ml-1.5 font-normal text-muted-foreground">· cheaper option, with tradeoffs</span>
                  </p>
                  {altResult.strategy && (
                    <p className="text-lg font-bold text-foreground">{altResult.strategy}</p>
                  )}
                  <div className="grid grid-cols-3 gap-4 pt-0.5">
                    <div className="bg-secondary border border-border rounded-md p-5">
                      <p className="text-xs text-muted-foreground mb-2">Cost to enter</p>
                      <p className="font-mono text-3xl font-semibold tabular-nums">
                        {altCostToEnter != null ? `$${Math.round(altCostToEnter).toLocaleString()}` : "—"}
                      </p>
                    </div>
                    <div className="bg-secondary border border-border rounded-md p-5">
                      <p className="text-xs text-muted-foreground mb-2">Max loss</p>
                      <p className="font-mono text-3xl font-semibold tabular-nums text-destructive">
                        {altMaxLoss != null ? `$${Math.round(altMaxLoss).toLocaleString()}` : "—"}
                      </p>
                    </div>
                    <div className="bg-secondary border border-border rounded-md p-5">
                      <p className="text-xs text-muted-foreground mb-2">Max gain</p>
                      {altIsUnlimited ? (
                        <p className="text-xl font-semibold text-success">Unlimited</p>
                      ) : (
                        <p className="font-mono text-3xl font-semibold tabular-nums text-success">
                          {altMaxGain != null ? `$${Math.round(altMaxGain).toLocaleString()}` : "—"}
                        </p>
                      )}
                    </div>
                  </div>
                  {altResult.target != null && (
                    <p className="text-xs text-muted-foreground">
                      Target: <span className="text-foreground font-medium">${altResult.target.toFixed(2)}</span>
                    </p>
                  )}
                  {altResult.tradeoff && (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      <span className="font-medium text-foreground">Tradeoff:</span>{" "}
                      {altResult.tradeoff}
                    </p>
                  )}
                  {altResult.reasoning && (
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {altResult.reasoning}
                    </p>
                  )}
                </div>
              )}

              {altResult != null && !altResult.fits && (
                <Callout severity="caution" title="Nothing good fits this budget">
                  {altResult.note}
                </Callout>
              )}
            </>
          )}
        </div>
      )}

      <p className="text-xs text-muted-foreground italic">
        Data-grounded suggestion — not a recommendation. Review carefully before saving.
      </p>

      {/* K) CTA row */}
      <div className="flex gap-3 pt-1">
        <button
          type="button"
          onClick={handleAccept}
          className="rounded-xl bg-primary text-primary-foreground px-6 py-3.5 text-sm font-medium hover:opacity-90 transition-opacity"
        >
          Continue with this trade →
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="rounded-xl border border-border text-muted-foreground hover:text-foreground px-5 py-3.5 text-sm bg-transparent transition-colors"
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
              ? "bg-cool border-cool text-white"
              : "border-border text-muted-foreground hover:border-cool/50 hover:text-foreground",
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

function BuildTradePageContent() {
  const searchParams = useSearchParams();
  const tickerParam = searchParams.get("ticker");

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
  const [direction, setDirection] = useState<"bullish" | "bearish" | "auto" | null>(null);
  const [aggressiveness, setAggressiveness] = useState<"conservative" | "moderate" | "aggressive">("moderate");
  const [alertPick, setAlertPick] = useState<AlertPickRead | null>(null);

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
  const [notes, setNotes] = useState("");
  const [optionLeg, setOptionLeg] = useState<OptionLegDraft | null>(null);
  const [contracts, setContracts] = useState("1");
  const [saveError, setSaveError] = useState<string | null>(null);

  // Result
  const [savedThesis, setSavedThesis] = useState<Thesis | null>(null);

  // Recent searches (client-only localStorage)
  const [recents, setRecents] = useState<RecentTicker[]>([]);
  useEffect(() => { setRecents(readRecents()); }, []);

  useEffect(() => {
    api.tickers.list().then((list) => {
      setTickers(list);
      if (tickerParam) {
        const sym = tickerParam.toUpperCase();
        const match = list.find((t) => t.symbol.toUpperCase() === sym);
        if (match) handleSelectTicker(match);
        // invalid param: falls through — step stays pick_stock, picker stays empty
      }
    }).catch(() => null).finally(() => setTickersLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSelectTicker(t: Ticker) {
    setSelectedTicker(t);
    setQuote(null);
    setQuoteLoading(true);
    setStep("pick_direction");
    pushRecent({ symbol: t.symbol, name: t.name });
    setRecents(readRecents());
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
    setAlertPick(null);
    setStep("pick_stock");
  }

  function pickDirection(d: "bullish" | "bearish") {
    setDirection(d);
    setAlertPick(null);
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
      const d = await api.theses.draft({ symbol: selectedTicker.symbol, direction: direction as "bullish" | "bearish", aggressiveness });
      setDraft(d);
      setStep("review_draft");
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : "Generation failed — please try again");
      setStep("pick_direction");
    }
  }

  async function handleAlertPick() {
    if (!selectedTicker) return;
    setStep("generating");
    setDraftError(null);
    setAlertPick(null);
    try {
      const result = await api.theses.alertPick({ symbol: selectedTicker.symbol });
      setAlertPick(result);
      if (result.existing_pick) {
        // Duplicate refusal — show existing pick info, don't generate
        setStep("pick_direction");
        setDirection(null);
      } else if (result.picked_direction === "mixed_evidence") {
        setStep("pick_direction");
        setDirection(null);         // reset so user can pick manually
      } else {
        setDirection(result.picked_direction as "bullish" | "bearish");
        setDraft(result.draft);
        setStep("review_draft");
      }
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : "Generation failed");
      setStep("pick_direction");
      setDirection(null);
    }
  }

  function handleAcceptDraft(target: number | null, draftReasoning: string, leg: OptionLegDraft | null) {
    if (target != null) setPriceTarget(target.toFixed(2));
    setOptionLeg(leg);
    setStep("confirm");
  }

  async function handleSave() {
    if (!selectedTicker || !direction) return;
    // Resolve "auto" direction to the actual picked direction for saving
    const saveDirection: "bullish" | "bearish" =
      direction === "auto" && alertPick ? (alertPick.picked_direction as "bullish" | "bearish") : (direction as "bullish" | "bearish");
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
        direction: saveDirection,
        conviction,
        target_date: targetDate,
        ...(priceTarget ? { price_target: parseFloat(priceTarget) } : {}),
        ...(draft?.reasoning ? { reasoning: draft.reasoning } : {}),
        ...(notes.trim() ? { notes: notes.trim() } : {}),
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
    setAlertPick(null);
    setConviction(3);
    setTargetDate(defaultTargetDate());
    setPriceTarget("");
    setNotes("");
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
              {(direction === "auto" && alertPick ? alertPick.picked_direction : direction) === "bullish" ? "Bullish" : "Bearish"} thesis on{" "}
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
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Build a Trade</h1>
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
                <div className="space-y-4">
                  <TickerPicker tickers={tickers} onSelect={handleSelectTicker} />

                  {/* Recent searches */}
                  {recents.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Recent</p>
                      <div className="flex flex-wrap gap-2">
                        {recents.map((r) => {
                          const match = tickers.find((t) => t.symbol === r.symbol);
                          return (
                            <button
                              key={r.symbol}
                              type="button"
                              disabled={!match}
                              onClick={() => match && handleSelectTicker(match)}
                              className="flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-sm transition-colors hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                              <span className="font-display font-bold">{r.symbol}</span>
                              {r.name && (
                                <span className="text-muted-foreground text-xs truncate max-w-[120px]">{r.name}</span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )
            ) : (
              <div className="flex items-center justify-between rounded-[var(--radius)] border border-border bg-card px-5 py-3.5">
                <div className="flex items-center gap-4 min-w-0">
                  <span className="text-2xl font-display font-bold tracking-tight text-foreground">{selectedTicker.symbol}</span>
                  {selectedTicker.name && (
                    <span className="text-sm text-muted-foreground truncate hidden sm:block">
                      {selectedTicker.name}
                    </span>
                  )}
                  <span className="font-mono text-sm font-semibold tabular-nums shrink-0 text-foreground">
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
                  className="text-xs text-cool hover:text-cool/80 transition-colors ml-4 shrink-0"
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

              {/* Duplicate-refusal — Alert already has an open pick on this symbol */}
              {alertPick?.existing_pick && (
                <div className="rounded-lg border border-orange-500/30 bg-orange-500/5 px-5 py-4 space-y-3 mb-4">
                  <p className="text-sm font-medium">
                    Alert already has an open {alertPick.picked_direction} pick on {alertPick.symbol} from{" "}
                    {new Date(alertPick.generated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                  </p>
                  <p className="text-xs text-muted-foreground">One open pick per symbol. Pick a direction manually below, or close the existing pick first.</p>
                </div>
              )}

              {/* Mixed-evidence fallback — shown when Alert couldn't pick */}
              {alertPick?.picked_direction === "mixed_evidence" && !alertPick?.existing_pick && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-5 py-4 space-y-3 mb-4">
                  <p className="text-sm font-medium">Evidence conflicts — Alert can&apos;t pick a clear direction</p>
                  <div className="text-xs text-muted-foreground space-y-1.5">
                    {alertPick.leans.map((lean) => (
                      <div key={lean.signal} className="flex items-start gap-2">
                        <span className={cn(
                          "mt-0.5 w-2 h-2 rounded-full shrink-0",
                          lean.direction === "bullish" ? "bg-green-500" :
                          lean.direction === "bearish" ? "bg-red-500" : "bg-zinc-400"
                        )} />
                        <span>
                          <span className="font-medium capitalize">{lean.signal}:</span>{" "}
                          {lean.justification}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">Pick a direction manually below.</p>
                </div>
              )}

              <div className={cn("grid gap-4", (alertPick?.picked_direction === "mixed_evidence" || alertPick?.existing_pick) ? "grid-cols-2" : "grid-cols-3")}>
                <button
                  type="button"
                  onClick={() => pickDirection("bullish")}
                  className={cn(
                    "py-8 rounded-[var(--radius)] border text-center transition-all select-none",
                    direction === "bullish"
                      ? "bg-success/10 border-success text-success"
                      : "border-border text-muted-foreground hover:border-success/50 hover:bg-success/5",
                  )}
                >
                  <GiBull aria-hidden="true" className="w-9 h-9 mx-auto mb-2" />
                  <div className="text-base font-bold">Bullish</div>
                  <div className="text-xs opacity-60 mt-1">expecting the stock price to rise</div>
                </button>

                <button
                  type="button"
                  onClick={() => pickDirection("bearish")}
                  className={cn(
                    "py-8 rounded-[var(--radius)] border text-center transition-all select-none",
                    direction === "bearish"
                      ? "bg-destructive/10 border-destructive text-destructive"
                      : "border-border text-muted-foreground hover:border-destructive/50 hover:bg-destructive/5",
                  )}
                >
                  <GiBearFace aria-hidden="true" className="w-9 h-9 mx-auto mb-2" />
                  <div className="text-base font-bold">Bearish</div>
                  <div className="text-xs opacity-60 mt-1">expecting the stock price to fall</div>
                </button>

                {/* "Let Alert decide" — hidden after mixed_evidence or duplicate refusal */}
                {alertPick?.picked_direction !== "mixed_evidence" && !alertPick?.existing_pick && (
                  <button
                    type="button"
                    onClick={() => { setDirection("auto"); handleAlertPick(); }}
                    disabled={step === "generating"}
                    className={cn(
                      "py-8 rounded-[var(--radius)] border text-center transition-all select-none",
                      direction === "auto"
                        ? "bg-orange-500/10 border-orange-500 text-orange-600 dark:text-orange-400"
                        : "border-border text-muted-foreground hover:border-orange-500/50 hover:bg-orange-500/5",
                    )}
                  >
                    <HiSparkles aria-hidden="true" className="w-9 h-9 mx-auto mb-2" />
                    <div className="text-base font-bold">Let Alert decide</div>
                    <div className="text-xs opacity-60 mt-1">Alert picks from the data</div>
                  </button>
                )}
              </div>

              {/* Aggressiveness + generate (only for manual direction picks) */}
              {direction && direction !== "auto" && (step === "pick_direction" || step === "generating") && (
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

              {/* Generating spinner for auto mode */}
              {direction === "auto" && step === "generating" && (
                <p className="text-sm text-muted-foreground animate-pulse">Analyzing signals and generating trade…</p>
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

              {/* Alert's Pick leans panel */}
              {alertPick && alertPick.picked_direction !== "mixed_evidence" && (
                <div className="rounded-lg border border-orange-500/30 bg-orange-500/5 px-5 py-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wide text-orange-600 dark:text-orange-400">
                      Alert&apos;s Pick · {alertPick.picked_direction}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground space-y-1.5">
                    {alertPick.leans.map((lean) => (
                      <div key={lean.signal} className="flex items-start gap-2">
                        <span className={cn(
                          "mt-0.5 w-2 h-2 rounded-full shrink-0",
                          lean.direction === "bullish" ? "bg-green-500" :
                          lean.direction === "bearish" ? "bg-red-500" : "bg-zinc-400"
                        )} />
                        <span>
                          <span className="font-medium capitalize">{lean.signal}:</span>{" "}
                          {lean.justification}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="rounded-2xl border bg-card px-6 py-6">
                <DraftDisplay
                  draft={draft}
                  onAccept={handleAcceptDraft}
                  onRegenerate={() => { setStep("pick_direction"); setDraft(null); setAlertPick(null); }}
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
                    Notes
                  </label>
                  <textarea
                    rows={4}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Your own notes on this thesis (optional)"
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

export default function BuildTradePage() {
  return (
    <Suspense>
      <BuildTradePageContent />
    </Suspense>
  );
}
