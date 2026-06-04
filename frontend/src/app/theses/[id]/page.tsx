"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  api, type Thesis, type ThesisMarkRead, type StrategyData,
} from "@/lib/api";
import {
  BS_IV_DEFAULT,
  type Leg, dateMs,
} from "@/lib/black-scholes";
import { cn } from "@/lib/utils";
import PayoffSimulator from "@/components/PayoffSimulator";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(v: string): string {
  const [y, m, d] = v.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

function fmtDateShort(v: string): string {
  const [y, m, d] = v.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short", day: "numeric",
  });
}

function fmtOptionLeg(thesis: Thesis): string | null {
  if (!thesis.option_type || !thesis.strike) return null;
  const s1 = parseFloat(thesis.strike);
  const exp = thesis.option_expiration ? fmtDate(thesis.option_expiration) : "—";
  if (thesis.strike2) {
    const s2 = parseFloat(thesis.strike2);
    const name = thesis.option_type === "call" ? "Bull call spread" : "Bear put spread";
    return `${name} $${s1.toFixed(0)}/$${s2.toFixed(0)} · ${exp}`;
  }
  const name = thesis.option_type === "call" ? "Long call" : "Long put";
  return `${name} $${s1.toFixed(0)} · ${exp}`;
}

function fmtBasis(basis: ThesisMarkRead["mark_basis"]): string {
  switch (basis) {
    case "live_chain":    return "live chain";
    case "intrinsic":     return "intrinsic (expired)";
    case "not_found":     return "not found";
    case "no_option_leg": return "no option leg";
  }
}

// ── Build Leg[] from thesis ───────────────────────────────────────────────────

interface IVResult {
  legs: Leg[];
  usingFallback: boolean;
}

function buildLegs(thesis: Thesis, strategyData: StrategyData | null): IVResult | null {
  if (!thesis.option_type || !thesis.strike || !thesis.entry_premium) return null;
  const K1 = parseFloat(thesis.strike);
  const mid1 = parseFloat(thesis.entry_premium);
  const kind = thesis.option_type as "call" | "put";
  let usingFallback = false;

  function getIV(K: number, legKind: "call" | "put"): number {
    const row = strategyData?.strikes.find(s => s.strike === K);
    const atmRow = strategyData?.strikes.find(s => s.is_atm);
    const iv = legKind === "call"
      ? (row?.call_iv ?? atmRow?.call_iv ?? null)
      : (row?.put_iv  ?? atmRow?.put_iv  ?? null);
    if (iv == null) { usingFallback = true; return BS_IV_DEFAULT; }
    return iv;
  }

  if (thesis.strike2 && thesis.entry_premium2) {
    const K2 = parseFloat(thesis.strike2);
    const mid2 = parseFloat(thesis.entry_premium2);
    return {
      legs: [
        { kind, K: K1, mid: mid1, sigma: getIV(K1, kind), dir:  1, label: `Long $${K1} ${kind}` },
        { kind, K: K2, mid: mid2, sigma: getIV(K2, kind), dir: -1, label: `Short $${K2} ${kind}` },
      ],
      usingFallback,
    };
  }
  return {
    legs: [{ kind, K: K1, mid: mid1, sigma: getIV(K1, kind), dir: 1, label: `Long $${K1} ${kind}` }],
    usingFallback,
  };
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type LoadState = "loading" | "done" | "error";

export default function ThesisDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const [thesisState, setThesisState] = useState<LoadState>("loading");
  const [markState, setMarkState]     = useState<LoadState>("loading");
  const [sdState, setSdState]         = useState<LoadState>("loading");

  const [thesis, setThesis]             = useState<Thesis | null>(null);
  const [mark, setMark]                 = useState<ThesisMarkRead | null>(null);
  const [strategyData, setStrategyData] = useState<StrategyData | null>(null);
  const [thesisError, setThesisError]   = useState<string | null>(null);
  const [markError, setMarkError]       = useState<string | null>(null);
  const [reasoningOpen, setReasoningOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.theses.get(id)
      .then(t => {
        setThesis(t);
        setThesisState("done");
        api.theses.mark(id)
          .then(m => { setMark(m); setMarkState("done"); })
          .catch(e => { setMarkError(String(e)); setMarkState("error"); });
        if (t.ticker_symbol) {
          api.tickers.strategyData(t.ticker_symbol)
            .then(sd => { setStrategyData(sd); setSdState("done"); })
            .catch(() => { setSdState("error"); });
        } else {
          setSdState("done");
        }
      })
      .catch(e => {
        setThesisError(String(e));
        setThesisState("error");
        setMarkState("error");
        setSdState("error");
      });
  }, [id]);

  // Build legs once thesis + strategyData are ready
  const ivResult = useMemo(() => {
    if (!thesis) return null;
    return buildLegs(thesis, strategyData);
  }, [thesis, strategyData]);

  const legs = ivResult?.legs ?? null;
  const usingIVFallback = ivResult?.usingFallback ?? false;
  const sdFailed = sdState === "error" && thesis?.option_type != null;

  // ── Simulator inputs — kept here; passed as props ─────────────────────────

  const expMs = thesis?.option_expiration ? dateMs(thesis.option_expiration) : null;

  const cp = mark?.current_price ?? (strategyData?.current_price ?? null);
  const initialScrub = cp ?? (thesis?.entry_price ? parseFloat(thesis.entry_price) : 100);

  const mult = thesis ? thesis.contracts * 100 : 100;

  // x-axis range — fallback-resolved here, passed as xMin/xMax
  const xRange = useMemo(() => {
    const irLo = strategyData?.implied_range_low;
    const irHi = strategyData?.implied_range_high;
    const base = cp ?? initialScrub;
    if (irLo != null && irHi != null) {
      const pad = (irHi - irLo) * 0.30;
      return { lo: irLo - pad, hi: irHi + pad };
    }
    return { lo: base * 0.80, hi: base * 1.20 };
  }, [strategyData, cp, initialScrub]);

  const earningsDateMs = strategyData?.earnings_date ? dateMs(strategyData.earnings_date) : null;

  // ── Mark panel helpers ────────────────────────────────────────────────────

  const pnlDollars = mark?.pnl_dollars ?? null;
  const pnlPct = mark?.pnl_pct ?? null;
  const pnlColor = pnlDollars == null
    ? "text-muted-foreground"
    : pnlDollars > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : pnlDollars < 0
        ? "text-red-500 dark:text-red-400"
        : "text-foreground";

  const pnlStr = pnlDollars == null
    ? "—"
    : `${pnlDollars >= 0 ? "+" : "−"}$${Math.abs(pnlDollars).toLocaleString("en-US", {
        minimumFractionDigits: 0, maximumFractionDigits: 0,
      })}${pnlPct != null ? ` (${pnlPct >= 0 ? "+" : ""}${(pnlPct * 100).toFixed(1)}%)` : ""}`;

  // ── Loading / error states ────────────────────────────────────────────────

  if (thesisState === "loading") {
    return (
      <div className="max-w-3xl mx-auto px-4 py-10 text-sm text-muted-foreground">
        Loading thesis…
      </div>
    );
  }

  if (thesisState === "error" || !thesis) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-10">
        <Link href="/theses" className="text-sm text-muted-foreground hover:text-foreground">
          ← Back to Tracker
        </Link>
        <p className="mt-4 text-sm text-destructive">{thesisError ?? "Thesis not found."}</p>
      </div>
    );
  }

  const hasOption = Boolean(thesis.option_type && thesis.strike);
  const optionLegStr = fmtOptionLeg(thesis);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="space-y-1">
        <Link href="/theses" className="text-sm text-muted-foreground hover:text-foreground">
          ← Back to Tracker
        </Link>
        <div className="flex items-center gap-2 flex-wrap mt-2">
          <h1 className="text-xl font-semibold">
            {thesis.ticker_symbol}
            <span className="text-muted-foreground font-normal"> · </span>
            <span className={
              thesis.direction === "bullish" ? "text-emerald-600 dark:text-emerald-400" :
              thesis.direction === "bearish" ? "text-red-500 dark:text-red-400" :
              "text-slate-500"
            }>{thesis.direction}</span>
            {optionLegStr && (
              <>
                <span className="text-muted-foreground font-normal"> · </span>
                <span className="text-base font-normal">{optionLegStr}</span>
              </>
            )}
          </h1>
        </div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>{"★".repeat(thesis.conviction)}{"☆".repeat(5 - thesis.conviction)}</span>
          {thesis.catalyst && <span>· {thesis.catalyst}</span>}
          <span>· By {fmtDate(thesis.target_date)}</span>
          {thesis.entry_price && (
            <span>· Entry ${parseFloat(thesis.entry_price).toFixed(2)}</span>
          )}
        </div>
        {thesis.reasoning && (
          <div className="mt-1">
            <button
              type="button"
              onClick={() => setReasoningOpen(o => !o)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              {reasoningOpen ? "▾" : "▸"} Reasoning
            </button>
            {reasoningOpen && (
              <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{thesis.reasoning}</p>
            )}
          </div>
        )}
      </div>

      {/* ── No option leg ──────────────────────────────────────────────────── */}
      {!hasOption && (
        <div className="rounded-lg border bg-muted/20 px-5 py-4 text-sm text-muted-foreground">
          This thesis does not have an option leg tracked. No live mark or simulator available.
        </div>
      )}

      {hasOption && (
        <div className="space-y-4">

          {/* ── Panel 1: Live Mark ───────────────────────────────────────── */}
          <div className="rounded-lg border bg-card px-5 py-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400 text-xs font-medium px-2 py-0.5 rounded-full">
                LIVE MARK
              </span>
              {mark?.is_expired && (
                <span className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 text-xs font-medium px-2 py-0.5 rounded-full">
                  EXPIRED
                </span>
              )}
            </div>

            {markState === "loading" && (
              <p className="text-sm text-muted-foreground">Loading mark…</p>
            )}
            {markState === "error" && (
              <p className="text-sm text-destructive">{markError ?? "Failed to load mark."}</p>
            )}
            {markState === "done" && mark && (
              <>
                <p className={cn("text-3xl font-bold tabular-nums tracking-tight leading-none", pnlColor)}>
                  {pnlStr}
                </p>
                <p className="text-xs text-muted-foreground">
                  Basis: {fmtBasis(mark.mark_basis)}
                  {mark.current_price != null && ` · ${thesis.ticker_symbol} @ $${mark.current_price.toFixed(2)}`}
                </p>
                {mark.mark_note && (
                  <p className="text-xs text-muted-foreground">{mark.mark_note}</p>
                )}
              </>
            )}
          </div>

          {/* ── Panel 2: Simulator ──────────────────────────────────────── */}
          {legs && expMs != null && (
            <PayoffSimulator
              legs={legs}
              spot={initialScrub}
              currentPrice={cp}
              symbol={thesis.ticker_symbol ?? ""}
              expirationMs={expMs}
              mult={mult}
              xMin={xRange.lo}
              xMax={xRange.hi}
              earningsMs={earningsDateMs}
              usingIVFallback={usingIVFallback}
              sdFailed={sdFailed}
            />
          )}
        </div>
      )}
    </div>
  );
}
