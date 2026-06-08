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
import { buildPlainEnglish } from "@/lib/plain-english";
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

  // ── P&L: three states ───────────────────────────────────────────────────────

  const hasOption = thesis ? Boolean(thesis.option_type && thesis.strike) : false;
  const isResolved = thesis?.status === "resolved";
  const isExpired = mark?.is_expired ?? false;

  let pnlDollars: number | null = null;
  let pnlPct: number | null = null;
  let pnlLabel = "Live P&L";

  if (isResolved && thesis?.option_pnl_dollars != null) {
    // State 1: Resolved — snapshotted on the Thesis record
    pnlDollars = parseFloat(thesis.option_pnl_dollars);
    pnlPct = thesis.option_pnl_pct != null ? parseFloat(thesis.option_pnl_pct) : null;
    pnlLabel = "Closed P&L";
  } else if (isExpired && !isResolved) {
    // State 2: Expired but not yet resolved — intrinsic settlement
    pnlDollars = mark?.pnl_dollars ?? null;
    pnlPct = mark?.pnl_pct ?? null;
    pnlLabel = "Expired (intrinsic)";
  } else {
    // State 3: Active — live chain mark
    pnlDollars = mark?.pnl_dollars ?? null;
    pnlPct = mark?.pnl_pct ?? null;
    pnlLabel = "Live P&L";
  }

  const pnlColor = pnlDollars == null
    ? "text-muted-foreground"
    : pnlDollars > 0
      ? "text-success"
      : pnlDollars < 0
        ? "text-destructive"
        : "text-foreground";

  const pnlDollarStr = pnlDollars == null
    ? "—"
    : `${pnlDollars >= 0 ? "+" : "−"}$${Math.abs(pnlDollars).toLocaleString("en-US", {
        minimumFractionDigits: 0, maximumFractionDigits: 0,
      })}`;

  const pnlPctStr = pnlPct != null
    ? `${pnlPct >= 0 ? "+" : ""}${(pnlPct * 100).toFixed(1)}%`
    : null;

  // ── Cost basis ──────────────────────────────────────────────────────────────

  const costBasis = (() => {
    if (!thesis?.entry_premium) return null;
    const p1 = parseFloat(thesis.entry_premium);
    if (thesis.strike2 && thesis.entry_premium2) {
      const p2 = parseFloat(thesis.entry_premium2);
      return (p1 - p2) * thesis.contracts * 100;
    }
    return p1 * thesis.contracts * 100;
  })();

  // ── Trade description pieces ────────────────────────────────────────────────

  const tradeName = (() => {
    if (!thesis?.option_type || !thesis.strike) return null;
    if (thesis.strike2) {
      return thesis.option_type === "call" ? "Bull call spread" : "Bear put spread";
    }
    return thesis.option_type === "call" ? "Long call" : "Long put";
  })();

  const strikeStr = (() => {
    if (!thesis?.strike) return null;
    const s1 = parseFloat(thesis.strike).toFixed(0);
    if (thesis.strike2) {
      const s2 = parseFloat(thesis.strike2).toFixed(0);
      return `${s1}/${s2}`;
    }
    return s1;
  })();

  const expStr = thesis?.option_expiration ? fmtDateShort(thesis.option_expiration) : null;

  // ── Plain-English reasoning (from entry premiums, total dollars) ────────────

  const plainEnglish = useMemo(() => {
    if (!thesis || !hasOption) return null;
    const strike = thesis.strike ? parseFloat(thesis.strike) : null;
    const spreadStrike = thesis.strike2 ? parseFloat(thesis.strike2) : null;
    const leg1Mid = thesis.entry_premium ? parseFloat(thesis.entry_premium) : null;
    const leg2Mid = thesis.entry_premium2 ? parseFloat(thesis.entry_premium2) : null;
    const isSpread = Boolean(thesis.strike2);
    const netDebit = isSpread && leg1Mid != null && leg2Mid != null ? leg1Mid - leg2Mid : null;
    const spreadWidth = strike != null && spreadStrike != null ? Math.abs(spreadStrike - strike) : null;
    const contracts = thesis.contracts || 1;
    const shortName = isSpread
      ? (thesis.direction === "bullish" ? "Bull call spread" : "Bear put spread")
      : `Long ${thesis.direction === "bullish" ? "call" : "put"}`;

    const cost = costBasis;   // total (× contracts × 100), matches hero
    const maxLoss = costBasis;
    const maxGain: number | "unlimited" | null = isSpread
      ? (spreadWidth != null && netDebit != null ? (spreadWidth - netDebit) * contracts * 100 : null)
      : thesis.direction === "bullish"
        ? "unlimited"
        : (strike != null && leg1Mid != null ? (strike - leg1Mid) * contracts * 100 : null);
    const breakeven = isSpread
      ? (strike != null && netDebit != null
          ? (thesis.direction === "bullish" ? strike + netDebit : strike - netDebit)
          : null)
      : (strike != null && leg1Mid != null
          ? (thesis.direction === "bullish" ? strike + leg1Mid : strike - leg1Mid)
          : null);

    return buildPlainEnglish({
      shortName,
      direction: thesis.direction,
      isSpread,
      symbol: thesis.ticker_symbol ?? "",
      strike,
      spreadStrike,
      cost,
      maxLoss,
      maxGain,
      netDebit,
      breakeven,
      expiration: thesis.option_expiration ?? null,
    });
  }, [thesis, hasOption, costBasis]);

  const [reasoningMode, setReasoningMode] = useState<"plain" | "detailed">("detailed");

  // ── Direction pill + state badge ────────────────────────────────────────────

  const dirPillClass = thesis?.direction === "bullish"
    ? "bg-success/10 text-success"
    : thesis?.direction === "bearish"
      ? "bg-destructive/10 text-destructive"
      : "bg-muted text-muted-foreground";

  const stateBadge = isResolved
    ? { label: "CLOSED", cls: "bg-muted text-muted-foreground" }
    : isExpired
      ? { label: "EXPIRED", cls: "bg-primary/10 text-primary" }
      : { label: "LIVE", cls: "bg-success/10 text-success" };

  // ── Loading / error states ──────────────────────────────────────────────────

  if (thesisState === "loading") {
    return (
      <div className="max-w-3xl mx-auto px-4 py-10 space-y-4">
        <div className="h-4 w-32 bg-secondary rounded animate-pulse" />
        <div className="h-64 bg-card border border-border rounded-2xl animate-pulse" />
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

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">

      <Link href="/theses" className="text-sm text-muted-foreground hover:text-foreground">
        ← Back to Tracker
      </Link>

      {/* ── Hero Card ──────────────────────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-2xl px-6 py-5 space-y-4">

        {/* Row 1: Ticker · direction pill · state badge */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-lg font-display font-semibold tracking-tight">
            {thesis.ticker_symbol}
          </span>
          <span className={cn(
            "text-[11px] font-semibold uppercase px-2 py-0.5 rounded-full",
            dirPillClass,
          )}>
            {thesis.direction}
          </span>
          <span className={cn(
            "text-[11px] font-semibold uppercase px-2 py-0.5 rounded-full inline-flex items-center gap-1",
            stateBadge.cls,
          )}>
            {!isResolved && !isExpired && (
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
            )}
            {stateBadge.label}
          </span>
        </div>

        {/* Row 2: Trade name with mono strikes */}
        {tradeName && strikeStr && (
          <p className="text-sm text-muted-foreground">
            {tradeName}{" "}
            <span className="font-mono text-foreground">{strikeStr}</span>
            {expStr && <span> · {expStr}</span>}
          </p>
        )}

        {/* Row 3: BIG P&L number */}
        {hasOption && (
          <div>
            {markState === "loading" ? (
              <div className="h-12 w-44 bg-secondary rounded animate-pulse" />
            ) : markState === "error" ? (
              <p className="text-sm text-destructive">{markError ?? "Failed to load mark."}</p>
            ) : (
              <>
                <p className={cn(
                  "text-[46px] font-mono font-bold tabular-nums tracking-tight leading-none",
                  pnlColor,
                )}>
                  {pnlDollarStr}
                  {pnlPctStr && (
                    <span className="text-lg font-semibold ml-2 opacity-70">{pnlPctStr}</span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground mt-1.5">
                  {pnlLabel}
                  {mark && <span> · {fmtBasis(mark.mark_basis)}</span>}
                </p>
              </>
            )}
          </div>
        )}

        {/* No option leg fallback */}
        {!hasOption && (
          <p className="text-sm text-muted-foreground">
            Stock-only thesis — no option leg tracked.
          </p>
        )}

        {/* Row 4: Price + cost strip */}
        <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
          {cp != null && (
            <span>Current <span className="font-mono text-foreground">${cp.toFixed(2)}</span></span>
          )}
          {thesis.entry_price && (
            <span>Entry <span className="font-mono text-foreground">${parseFloat(thesis.entry_price).toFixed(2)}</span></span>
          )}
          {thesis.price_target && (
            <span>Target <span className="font-mono text-foreground">${parseFloat(thesis.price_target).toFixed(2)}</span></span>
          )}
          {costBasis != null && (
            <span>
              Cost{" "}
              <span className="font-mono text-foreground">
                ${costBasis.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
              </span>
            </span>
          )}
          {thesis.contracts > 0 && hasOption && (
            <span>{thesis.contracts} contract{thesis.contracts !== 1 ? "s" : ""}</span>
          )}
        </div>
      </div>

      {/* ── Payoff Simulator ───────────────────────────────────────────────── */}
      {legs && expMs != null && (
        <div className="bg-secondary rounded-2xl p-4 space-y-3">
          <span className="inline-block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground bg-background/50 px-2.5 py-0.5 rounded">
            Payoff Simulator
          </span>
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
        </div>
      )}

      {/* ── Thesis Detail ──────────────────────────────────────────────────── */}
      <div className="space-y-4">
        {(thesis.reasoning || plainEnglish) && (
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Reasoning
              </h3>
              {plainEnglish != null && thesis.reasoning && (
                <div className="inline-flex rounded-lg border border-border bg-secondary p-0.5 text-xs font-medium">
                  {(["detailed", "plain"] as const).map((mode) => (
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
            </div>
            <p className="text-sm text-foreground leading-relaxed">
              {plainEnglish != null && reasoningMode === "plain" ? plainEnglish : thesis.reasoning}
            </p>
          </div>
        )}

        {thesis.notes && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
              Notes
            </h3>
            <p className="text-sm text-foreground leading-relaxed">{thesis.notes}</p>
          </div>
        )}

        <div className="flex items-center gap-3 text-sm flex-wrap">
          <span className="text-primary tracking-wide">
            {"★".repeat(thesis.conviction)}{"☆".repeat(5 - thesis.conviction)}
          </span>
          {thesis.catalyst && (
            <span className="text-foreground">{thesis.catalyst}</span>
          )}
          <span className="text-muted-foreground">By {fmtDate(thesis.target_date)}</span>
        </div>

        {mark?.mark_note && (
          <p className="text-xs text-muted-foreground">{mark.mark_note}</p>
        )}
      </div>
    </div>
  );
}
