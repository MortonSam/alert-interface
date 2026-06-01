"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  api, type Thesis, type ThesisMarkRead, type StrategyData,
} from "@/lib/api";
import {
  BS_R, BS_IV_DEFAULT, MS_PER_YEAR,
  type Leg, dateMs, multiLegPayoffPS, multiLegPayoffBSPS,
} from "@/lib/black-scholes";
import { cn } from "@/lib/utils";

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

// ── Chart helpers ─────────────────────────────────────────────────────────────

type ChartPoint = {
  price: number;
  pnl: number;
  pnl_pos: number | null;   // pnl when >= 0, else null  → green line
  pnl_neg: number | null;   // pnl when <  0, else null  → red line
};

/**
 * Split raw {price,pnl} series into green/red segments.
 * Inserts interpolated zero-crossing points so the two lines meet precisely at
 * pnl=0 without a gap or a diagonal bridge.
 */
function splitBySign(raw: Array<{ price: number; pnl: number }>): ChartPoint[] {
  const out: ChartPoint[] = [];
  for (let i = 0; i < raw.length; i++) {
    const d = raw[i];
    const prev = raw[i - 1];
    // Insert zero-crossing between prev and d when they straddle zero
    if (prev && d.pnl !== 0 && prev.pnl !== 0 && Math.sign(d.pnl) !== Math.sign(prev.pnl)) {
      const t = prev.pnl / (prev.pnl - d.pnl);   // interpolation fraction [0,1]
      const crossPrice = parseFloat((prev.price + t * (d.price - prev.price)).toFixed(2));
      out.push({ price: crossPrice, pnl: 0, pnl_pos: 0, pnl_neg: 0 });
    }
    out.push({
      price:   d.price,
      pnl:     d.pnl,
      pnl_pos: d.pnl >= 0 ? d.pnl : null,
      pnl_neg: d.pnl <  0 ? d.pnl : null,
    });
  }
  return out;
}

// ── PayoffYTick ───────────────────────────────────────────────────────────────

function PayoffYTick({
  x, y, payload,
}: {
  x?: number;
  y?: number;
  payload?: { value: number };
}) {
  if (x == null || y == null || !payload) return null;
  const v = payload.value;
  const color = v < 0 ? "#dc2626" : v > 0 ? "#16a34a" : "hsl(var(--muted-foreground))";
  const abs = Math.abs(Math.round(v)).toLocaleString("en-US");
  const label = v >= 0 ? `+$${abs}` : `-$${abs}`;
  return (
    <text x={x} y={y} fill={color} fontSize={10} textAnchor="end" dominantBaseline="middle">
      {label}
    </text>
  );
}

// ── SimTooltip ────────────────────────────────────────────────────────────────
// Reads .pnl from the raw data point (not from a series value) so it works
// regardless of which of the two colored Lines triggered the hover.

function SimTooltip({
  active, payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const pt = payload[0]?.payload;
  if (!pt) return null;
  const { price, pnl } = pt;
  const abs = Math.abs(pnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <div className="rounded border bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 shadow px-3 py-2 text-xs space-y-0.5">
      <p className="text-zinc-500 dark:text-zinc-400">
        Stock: <strong className="text-zinc-900 dark:text-zinc-100">${price.toFixed(2)}</strong>
      </p>
      <p style={{ color: pnl >= 0 ? "#16a34a" : "#dc2626" }} className="font-medium">
        Simulated: {pnl >= 0 ? "+" : "−"}${abs}
      </p>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type LoadState = "loading" | "done" | "error";

// Suppress the TS unused-variable warning for MS_PER_YEAR (imported per plan, unused here)
void MS_PER_YEAR;

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

  // ── Date & price simulator state ──────────────────────────────────────────

  const expMs = thesis?.option_expiration ? dateMs(thesis.option_expiration) : null;
  const nowMs = Date.now();
  const daysToExpiry = expMs != null ? Math.max(0, Math.round((expMs - nowMs) / 86400000)) : 0;
  const totalDays = Math.max(1, daysToExpiry);

  const cp = mark?.current_price ?? (strategyData?.current_price ?? null);
  const initialScrub = cp ?? (thesis?.entry_price ? parseFloat(thesis.entry_price) : 100);

  const [dateOffset, setDateOffset] = useState(0);
  const [scrubPrice, setScrubPrice] = useState<number>(initialScrub);

  useEffect(() => {
    if (cp != null) setScrubPrice(cp);
  }, [cp]);

  const T_slider = Math.max(0, (totalDays - dateOffset) / 365.25);
  const selectedDateMs = nowMs + dateOffset * 86400000;
  const selectedDateStr = new Date(selectedDateMs).toLocaleDateString("en-US", {
    month: "short", day: "numeric",
  });
  const daysLeft = Math.max(0, totalDays - dateOffset);

  const earningsDateMs = strategyData?.earnings_date ? dateMs(strategyData.earnings_date) : null;
  const showDisclaimer = earningsDateMs != null && selectedDateMs <= earningsDateMs;

  const mult = thesis ? thesis.contracts * 100 : 100;

  // x-axis range
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

  // Chart data — split into green/red segments at the zero crossover
  const chartData = useMemo((): ChartPoint[] => {
    if (!legs) return [];
    const { lo, hi } = xRange;
    const raw = Array.from({ length: 100 }, (_, i) => {
      const S = lo + (i / 99) * (hi - lo);
      const pnl = multiLegPayoffBSPS(legs, S, T_slider, BS_R) * mult;
      return { price: parseFloat(S.toFixed(2)), pnl: parseFloat(pnl.toFixed(2)) };
    });
    return splitBySign(raw);
  }, [legs, xRange, T_slider, mult]);

  // Stable y-domain (computed from at-expiry + today curves so axis doesn't jump while sliding)
  const yDomain = useMemo<[number, number]>(() => {
    if (!legs) return [-100, 100];
    const { lo, hi } = xRange;
    const vals: number[] = [];
    for (let i = 0; i < 100; i++) {
      const S = lo + (i / 99) * (hi - lo);
      vals.push(multiLegPayoffPS(legs, S) * mult);
      if (daysToExpiry > 0) {
        vals.push(multiLegPayoffBSPS(legs, S, daysToExpiry / 365.25, BS_R) * mult);
      }
    }
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const pad = (yMax - yMin) * 0.15 || 10;
    return [yMin - pad, yMax + pad];
  }, [legs, xRange, daysToExpiry, mult]);

  const scrubPoint = chartData.length
    ? chartData.reduce((best, d) =>
        Math.abs(d.price - scrubPrice) < Math.abs(best.price - scrubPrice) ? d : best)
    : null;
  const effectivePrice = scrubPoint?.price ?? scrubPrice;
  const scrubPnl: number | null = scrubPoint?.pnl ?? null;

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

  // ── IV display for simulator ──────────────────────────────────────────────

  const ivLabel = useMemo(() => {
    if (!legs) return null;
    if (legs.length === 1) return `${(legs[0].sigma * 100).toFixed(1)}%`;
    const ivs = legs.map(l => `${l.label.split(" ")[0]} ${l.label.split(" ")[1]}: ${(l.sigma * 100).toFixed(1)}%`);
    return ivs.join(" · ");
  }, [legs]);

  // ── Date slider geometry ──────────────────────────────────────────────────
  // thumbPct: 0% (Today) → 100% (Expiry), used for the visual fill + floating label
  const thumbPct = totalDays > 0 ? (dateOffset / totalDays) * 100 : 0;
  // Clamp label so it doesn't overflow the container at extremes
  const labelLeft = Math.max(7, Math.min(93, thumbPct));
  // What to show in the floating thumb label
  const thumbLabel = dateOffset === 0
    ? "Today"
    : daysLeft === 0
      ? "At expiry"
      : `${selectedDateStr} · ${daysLeft}d`;

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
          <div className="rounded-lg border border-dashed bg-muted/20 px-5 py-4 space-y-3">

            {/* Header pill — stays prominent so "this is modeled" is always clear */}
            <div className="flex items-center gap-2">
              <span className="bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-400 text-xs font-medium px-2 py-0.5 rounded-full">
                SIMULATED
              </span>
              <span className="text-xs text-muted-foreground">Black-Scholes projection</span>
            </div>

            {/* IV disclosure — always show what IV the simulation holds constant */}
            {ivLabel && !sdFailed && !usingIVFallback && (
              <p className="text-xs text-muted-foreground">
                Simulated at IV {ivLabel} (held constant)
              </p>
            )}
            {(sdFailed || usingIVFallback) && (
              <p className="text-[11px] leading-relaxed text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2">
                <strong>
                  {sdFailed
                    ? "Could not load current IV for this strike — simulation uses a 30% default and may be inaccurate."
                    : "IV for one or more strikes not found — simulation uses a 30% default and may be inaccurate."}
                </strong>{" "}
                Real IV may differ significantly (e.g. high-vol names can be 50–80%).
              </p>
            )}

            {/* Hero simulated P&L */}
            <div className="py-1">
              <p className="text-xs text-muted-foreground mb-1.5">
                {thesis.ticker_symbol} at ${effectivePrice.toFixed(2)}
                {" · "}
                {daysLeft === 0 ? "At expiration" : selectedDateStr}
              </p>
              <p className={cn(
                "text-4xl font-bold tabular-nums tracking-tight leading-none",
                scrubPnl == null
                  ? "text-muted-foreground"
                  : scrubPnl >= 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-500 dark:text-red-400",
              )}>
                {scrubPnl == null
                  ? "—"
                  : `${scrubPnl >= 0 ? "+" : "−"}$${Math.abs(scrubPnl).toLocaleString("en-US", {
                      minimumFractionDigits: 2, maximumFractionDigits: 2,
                    })}`}
              </p>
            </div>

            {/* ── Payoff chart ──────────────────────────────────────────── */}
            {chartData.length > 0 && (
              <div className="relative">
                {/* SIMULATED watermark — keeps the "this is modeled" signal in the chart itself */}
                <div
                  className="absolute inset-0 flex items-center justify-center pointer-events-none select-none"
                  style={{ zIndex: 1 }}
                >
                  <span className="text-[11px] font-semibold tracking-widest text-indigo-400/25 dark:text-indigo-500/20 uppercase">
                    Simulated
                  </span>
                </div>

                <ResponsiveContainer width="100%" height={200}>
                  <LineChart
                    data={chartData}
                    margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                    onMouseMove={(e) => {
                      if (e.activeLabel != null) {
                        const p = parseFloat(String(e.activeLabel));
                        if (!isNaN(p)) setScrubPrice(p);
                      }
                    }}
                    onClick={(e) => {
                      if (e.activeLabel != null) {
                        const p = parseFloat(String(e.activeLabel));
                        if (!isNaN(p)) setScrubPrice(p);
                      }
                    }}
                  >
                    <CartesianGrid
                      strokeDasharray="2 6"
                      stroke="hsl(var(--border))"
                      strokeOpacity={0.4}
                      vertical={false}
                    />
                    <XAxis
                      dataKey="price"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                      tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      domain={yDomain}
                      tick={<PayoffYTick />}
                      axisLine={false}
                      tickLine={false}
                      width={68}
                    />
                    <Tooltip content={<SimTooltip />} />

                    {/* Zero line */}
                    <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />

                    {/* Current price marker */}
                    {cp != null && (
                      <ReferenceLine
                        x={cp}
                        stroke="hsl(var(--muted-foreground))"
                        strokeWidth={1}
                        strokeDasharray="3 5"
                        strokeOpacity={0.6}
                        label={{ value: "Current", position: "insideBottomRight", fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                      />
                    )}

                    {/* Price scrubber — neutral so it doesn't fight the green/red curve */}
                    <ReferenceLine
                      x={effectivePrice}
                      stroke="hsl(var(--foreground))"
                      strokeWidth={1.5}
                      strokeOpacity={0.7}
                    />

                    {/* Green: profit zone (pnl >= 0) */}
                    <Line
                      dataKey="pnl_pos"
                      stroke="#16a34a"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={false}
                      type={T_slider === 0 ? "linear" : "monotone"}
                      isAnimationActive={false}
                      connectNulls={false}
                    />
                    {/* Red: loss zone (pnl < 0) */}
                    <Line
                      dataKey="pnl_neg"
                      stroke="#dc2626"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={false}
                      type={T_slider === 0 ? "linear" : "monotone"}
                      isAnimationActive={false}
                      connectNulls={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ── Date slider ───────────────────────────────────────────── */}
            {thesis.option_expiration && (
              <div className="pt-2">
                {/*
                 * Custom overlay slider:
                 *   - Floating pill label above the thumb shows the selected date + DTE
                 *   - Filled indigo track from Today → thumb
                 *   - "Today" tick (left) and "Expiry DATE" tick (right) are always visible
                 *   - Native <input type="range"> overlaid invisibly handles all interactions
                 */}

                {/* Floating thumb label — rides with the handle */}
                <div className="relative h-7 mb-0.5 pointer-events-none select-none">
                  <div
                    className="absolute bottom-1 -translate-x-1/2 transition-none"
                    style={{ left: `${labelLeft}%` }}
                  >
                    <div className="bg-indigo-600 text-white text-[10px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap shadow-sm">
                      {thumbLabel}
                    </div>
                    {/* Connector line from pill to thumb */}
                    <div className="flex justify-center mt-0.5">
                      <div className="w-px h-1.5 bg-indigo-500 rounded-full" />
                    </div>
                  </div>
                </div>

                {/* Track + visual thumb + invisible native input */}
                <div className="relative h-5 flex items-center">
                  {/* Track background */}
                  <div className="absolute inset-x-0 h-1.5 rounded-full bg-border pointer-events-none" />
                  {/* Filled portion — Today → thumb */}
                  <div
                    className="absolute left-0 h-1.5 rounded-full bg-indigo-500 pointer-events-none transition-none"
                    style={{ width: `${thumbPct}%` }}
                  />
                  {/* Visual thumb circle */}
                  <div
                    className="absolute w-4 h-4 rounded-full bg-indigo-600 shadow ring-2 ring-white dark:ring-zinc-900 pointer-events-none transition-none"
                    style={{ left: `${thumbPct}%`, transform: "translateX(-50%)" }}
                  />
                  {/* Native input — transparent overlay, handles all drag interactions */}
                  <input
                    type="range"
                    min={0}
                    max={totalDays}
                    value={dateOffset}
                    onChange={(e) => setDateOffset(parseInt(e.target.value))}
                    className="absolute inset-0 w-full opacity-0 cursor-pointer"
                  />
                </div>

                {/* Endpoint labels with tick marks */}
                <div className="flex justify-between items-start mt-1.5 text-[10px] text-muted-foreground">
                  <div className="flex flex-col items-center gap-0.5">
                    <div className="w-px h-2 bg-border rounded-full" />
                    <span className="font-medium">Today</span>
                  </div>
                  <div className="flex flex-col items-center gap-0.5">
                    <div className="w-px h-2 bg-border rounded-full" />
                    <span>Expiry {fmtDateShort(thesis.option_expiration)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* IV-crush caveat */}
            {showDisclaimer && (
              <p className="text-[11px] leading-relaxed text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2">
                <strong>Note:</strong> This curve holds today&apos;s implied volatility constant.
                In practice, IV typically collapses after an earnings release — option values at
                or around earnings will likely be lower than shown.
              </p>
            )}

            {/* Footnote — keeps the "not a forecast" label visible at all times */}
            <p className="text-[10px] text-muted-foreground">
              Simulated values use Black-Scholes with IV held constant — not a forecast.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
